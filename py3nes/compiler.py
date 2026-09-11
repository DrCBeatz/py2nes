"""Lower runtime expressions and statements, and allocate their RAM symbols."""

from __future__ import annotations

from .ir import Add, Binary, Compare, Constant, If, Logical, Set, Variable, as_expr, walk_actions


class RuntimeCompiler:
    def __init__(self, variables=(), actors=(), collision=bytes(960), events=(), post_events=(), rooms=(),
                 modes=(), start_mode=0):
        self.variables = tuple(variables)
        self.rooms = tuple(rooms)
        self.modes = tuple(modes)
        self._names = {}
        self._symbols = set()
        self._sequence = 0
        self._zp_size = 4  # controller and frame handshake bytes in codegen.py
        self._bss_size = 0
        self.zp = []
        self.bss = []
        self.init = []
        self.physics = None
        self.effects = None
        self.mode_runtime = None
        self.expr_rhs = self.reserve("rt_expr_rhs", zp=True)
        if self.rooms:
            for name in ("room", "room_next", "room_spawn", "room_pending", "room_loading"):
                self.reserve("rt_" + name)
        for variable in self.variables:
            label = self.reserve("v_" + variable.name)
            self._names[id(variable)] = label
            self.init += [f"    lda #${variable.initial & 255:02X}", f"    sta {label}"]
        if self.modes:
            from .modes_codegen import ModesRuntime
            self.mode_runtime = ModesRuntime(self, self.modes, start_mode)
            self.init += self.mode_runtime.prepare_init
        if actors:
            from .physics_codegen import PhysicsRuntime
            self.physics = PhysicsRuntime(self, actors, collision, rooms=self.rooms)
            if not self.rooms:
                self.init += self.physics.init
        room_events = tuple(e for room in self.rooms
                            for e in (*room.events, *room.post_events, *room.enter_events))
        mode_events = tuple(e for mode in self.modes for e in mode.enter_events)
        actions = tuple(walk_actions(a for event in (*events, *post_events, *room_events, *mode_events) for a in event.actions))
        # Keep the state-only compiler independently usable as the runtime grows.
        from .effects import write_count
        from .effects_codegen import EffectsRuntime
        self.effects = EffectsRuntime(self, actions)
        self.init += self.effects.init
        global_events = (*events, *post_events)
        global_cost = self.event_costs(global_events, write_count)
        costs = [global_cost]
        for room in self.rooms:
            costs.append(self.event_costs((*global_events, *room.events, *room.post_events), write_count))
            costs.append(sum(self.action_costs(e.actions, write_count) for e in room.enter_events))
        costs += [sum(self.action_costs(e.actions, write_count) for e in mode.enter_events)
                  for mode in self.modes]
        if max(costs) > 64:
            raise ValueError(f"events may enqueue {max(costs)} background tile writes per tick or room entry; maximum is 64 (split work across ticks)")

    def event_costs(self, events, leaf_cost):
        events = tuple(events)
        if not self.modes:
            return sum(self.action_costs(event.actions, leaf_cost) for event in events)
        return max(sum(self.action_costs(event.actions, leaf_cost) for event in events
                       if event.scope == "always" or event.scope is mode
                       or ((event.scope is None or event.scope == "gameplay") and mode.gameplay))
                   for mode in self.modes)

    @staticmethod
    def action_costs(actions, leaf_cost):
        """Maximum writes along a path, stopping at unconditional transitions.

        Ordinary ChangeMode can be a same-mode no-op, so its continuation still
        counts. Guarded sequence transitions use restart=True to expose their
        terminal path without counting the sequence finalizer twice.
        """
        from .modes import ChangeMode
        from .rooms import ChangeRoom

        def maximum(*values):
            values = tuple(value for value in values if value is not None)
            return max(values) if values else None

        def paths(commands):
            continuing, terminated = 0, None
            for action in commands:
                if continuing is None:
                    break
                if isinstance(action, If):
                    left, right = paths(action.actions), paths(action.otherwise)
                    advance, stop = maximum(left[0], right[0]), maximum(left[1], right[1])
                elif isinstance(action, ChangeRoom) or isinstance(action, ChangeMode) and action.restart:
                    advance, stop = None, 0
                else:
                    advance, stop = leaf_cost(action), None
                if stop is not None:
                    terminated = maximum(terminated, continuing + stop)
                continuing = continuing + advance if advance is not None else None
            return continuing, terminated

        return maximum(*paths(actions)) or 0

    def unique(self, prefix="branch"):
        self._sequence += 1
        return f"rt_{prefix}_{self._sequence}"

    def reserve(self, name, size=1, zp=False):
        if name in self._symbols:
            raise ValueError(f"duplicate runtime symbol: {name}")
        self._symbols.add(name)
        if zp:
            self._zp_size += size
            if self._zp_size > 256:
                raise ValueError("runtime zero-page allocation exceeds 256 bytes")
            self.zp += [f".exportzp {name}", f"{name}: .res {size}"]
        else:
            self._bss_size += size
            if self._bss_size > 1280:
                raise ValueError("runtime RAM allocation exceeds $0300-$07FF (1280 bytes)")
            self.bss += [f".export {name}", f"{name}: .res {size}"]
        return name

    def var(self, variable):
        try:
            return self._names[id(variable)]
        except KeyError:
            raise ValueError(f"unregistered runtime variable {variable.name!r}") from None

    def load(self, expression, depth=0):
        if depth > 32:
            raise ValueError("runtime expressions may nest at most 32 levels")
        expression = as_expr(expression)
        if isinstance(expression, Constant):
            return [f"    lda #${expression.value & 255:02X}"]
        if isinstance(expression, Variable):
            return [f"    lda {self.var(expression)}"]
        if isinstance(expression, Binary):
            code = self.load(expression.left, depth + 1) + ["    pha"]
            code += self.load(expression.right, depth + 1)
            code += [f"    sta {self.expr_rhs}", "    pla"]
            if expression.operator == "+": code += ["    clc", f"    adc {self.expr_rhs}"]
            elif expression.operator == "-": code += ["    sec", f"    sbc {self.expr_rhs}"]
            else:
                instruction = {"&": "and", "|": "ora", "^": "eor"}[expression.operator]
                code.append(f"    {instruction} {self.expr_rhs}")
            return code
        raise TypeError(f"unsupported runtime expression: {type(expression).__name__}")

    def condition(self, condition, false_label, depth=0):
        """Fall through on true; absolute-jump on false without branch range limits."""
        if depth > 32:
            raise ValueError("runtime conditions may nest at most 32 levels")
        if self.mode_runtime:
            result = self.mode_runtime.condition(condition, false_label)
            if result is not None:
                return result
        from .controls import ButtonDown
        from .sequences import ButtonPressed
        if isinstance(condition, (ButtonDown, ButtonPressed)):
            state = "controller_pressed" if isinstance(condition, ButtonPressed) else "controller_held"
            passed = self.unique("button_test")
            return [f"    lda {state}", f"    and #${int(condition.button):02X}",
                    f"    bne {passed}", f"    jmp {false_label}", f"{passed}:"]
        if isinstance(condition, Compare):
            code = self.load(condition.left)
            if condition.signed: code.append("    eor #$80")
            code += ["    pha"] + self.load(condition.right)
            if condition.signed: code.append("    eor #$80")
            code += [f"    sta {self.expr_rhs}", "    pla", f"    cmp {self.expr_rhs}"]
            passed = self.unique("compare_true")
            branches = {"eq": [f"    beq {passed}"], "ne": [f"    bne {passed}"],
                        "lt": [f"    bcc {passed}"], "ge": [f"    bcs {passed}"],
                        "le": [f"    bcc {passed}", f"    beq {passed}"]}
            if condition.operator == "gt":
                failed = self.unique("compare_false")
                code += [f"    beq {failed}", f"    bcs {passed}", f"{failed}:"]
            else:
                code += branches[condition.operator]
            return code + [f"    jmp {false_label}", f"{passed}:"]
        if isinstance(condition, Logical):
            if condition.operator == "and":
                return self.condition(condition.left, false_label, depth + 1) + self.condition(condition.right, false_label, depth + 1)
            if condition.operator == "or":
                right, done = self.unique("or_right"), self.unique("or_done")
                return (self.condition(condition.left, right, depth + 1) + [f"    jmp {done}", f"{right}:"]
                        + self.condition(condition.right, false_label, depth + 1) + [f"{done}:"])
            passed = self.unique("not_true")
            return self.condition(condition.left, passed, depth + 1) + [f"    jmp {false_label}", f"{passed}:"]
        if self.physics:
            result = self.physics.emit_condition(condition, false_label)
            if result is not None:
                return result
        from .combat_codegen import emit_condition
        result = emit_condition(self, condition, false_label)
        if result is not None:
            return result
        raise TypeError(f"unsupported runtime condition: {type(condition).__name__}")

    def action(self, action, depth=0):
        if depth > 32:
            raise ValueError("conditional actions may nest at most 32 levels")
        if self.mode_runtime:
            result = self.mode_runtime.action(action)
            if result is not None:
                return result
        from .rooms import ChangeRoom
        if isinstance(action, ChangeRoom):
            if not any(action.room is room for room in self.rooms):
                raise ValueError("room belongs to another game or was not registered")
            spawn = 255 if action.spawn is None else tuple(action.room.spawns).index(action.spawn)
            # Event bodies are subroutines; an early RTS also exits nested Ifs.
            # The main loop checks pending before running physics or more rules.
            return [f"    lda #{action.room.index}", "    sta rt_room_next",
                    f"    lda #{spawn}", "    sta rt_room_spawn",
                    "    lda #1", "    sta rt_room_pending", "    rts"]
        if isinstance(action, Set):
            return self.load(action.value) + [f"    sta {self.var(action.variable)}"]
        if isinstance(action, Add):
            return self.load(action.value) + ["    clc", f"    adc {self.var(action.variable)}", f"    sta {self.var(action.variable)}"]
        if isinstance(action, If):
            other, done = self.unique("else"), self.unique("endif")
            code = self.condition(action.condition, other)
            for item in action.actions: code += self.action(item, depth + 1)
            code += [f"    jmp {done}", f"{other}:"]
            for item in action.otherwise: code += self.action(item, depth + 1)
            return code + [f"{done}:"]
        for runtime in (self.physics, self.effects):
            if runtime is not None:
                code = runtime.emit_action(action)
                if code is not None: return code
        from .codegen import _action_lines
        return _action_lines(action)

    def events(self, events, label, *, scoped=True):
        from .model import Trigger
        code = [f".export {label}", f"{label}:"]
        for event in events:
            done = self.unique("event_done")
            if self.mode_runtime and scoped:
                code += self.mode_runtime.scope(event.scope, done)
            if event.trigger is not Trigger.FRAME:
                state = "controller_held" if event.trigger is Trigger.HELD else "controller_pressed"
                run = self.unique("event_run")
                code += [f"    lda {state}", f"    and #${int(event.button):02X}",
                         f"    bne {run}", f"    jmp {done}", f"{run}:"]
            for action in event.actions: code += self.action(action)
            code.append(f"{done}:")
        return code + ["    rts"]

    @property
    def report(self):
        return {"variables": len(self.variables), "zero_page_bytes": self._zp_size,
                "work_ram_bytes": self._bss_size}
