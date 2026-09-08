"""Lower runtime expressions and statements, and allocate their RAM symbols."""

from __future__ import annotations

from .ir import Add, Binary, Compare, Constant, If, Logical, Set, Variable, as_expr, walk_actions


class RuntimeCompiler:
    def __init__(self, variables=(), actors=(), collision=bytes(960), events=(), post_events=()):
        self.variables = tuple(variables)
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
        self.expr_rhs = self.reserve("rt_expr_rhs", zp=True)
        for variable in self.variables:
            label = self.reserve("v_" + variable.name)
            self._names[id(variable)] = label
            self.init += [f"    lda #${variable.initial & 255:02X}", f"    sta {label}"]
        if actors:
            from .physics_codegen import PhysicsRuntime
            self.physics = PhysicsRuntime(self, actors, collision)
            self.init += self.physics.init
        actions = tuple(walk_actions(a for event in (*events, *post_events) for a in event.actions))
        # Keep the state-only compiler independently usable as the runtime grows.
        from .effects import write_count
        from .effects_codegen import EffectsRuntime
        self.effects = EffectsRuntime(self, actions)
        self.init += self.effects.init
        cost = sum(self.action_costs(event.actions, write_count) for event in (*events, *post_events))
        if cost > 64:
            raise ValueError(f"events may enqueue {cost} background tile writes per tick; maximum is 64 (split work across ticks)")

    @staticmethod
    def action_costs(actions, leaf_cost):
        return sum(max(RuntimeCompiler.action_costs(action.actions, leaf_cost),
                       RuntimeCompiler.action_costs(action.otherwise, leaf_cost))
                   if isinstance(action, If) else leaf_cost(action) for action in actions)

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
        raise TypeError(f"unsupported runtime condition: {type(condition).__name__}")

    def action(self, action, depth=0):
        if depth > 32:
            raise ValueError("conditional actions may nest at most 32 levels")
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

    def events(self, events, label):
        from .model import Trigger
        code = [f".export {label}", f"{label}:"]
        for event in events:
            done = self.unique("event_done")
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
