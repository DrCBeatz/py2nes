"""Small mode scheduler; changing mode never executes Python at runtime."""

from .modes import ChangeMode, ModeActive


class ModesRuntime:
    def __init__(self, compiler, modes, start_mode=0):
        self.compiler, self.modes = compiler, tuple(modes)
        from .model import integer
        integer(start_mode, "start mode", 0, len(self.modes) - 1)
        for field in ("current", "next", "pending", "gameplay", "pause_music"):
            setattr(self, field, compiler.reserve("rt_mode_" + field))
        initial = self.modes[start_mode]
        self.prepare_init = [f"    lda #{start_mode}", f"    sta {self.current}",
                             f"    lda #{int(initial.gameplay)}", f"    sta {self.gameplay}",
                             f"    lda #{int(initial.pause_music)}", f"    sta {self.pause_music}"]
        self.init = [f"    lda #{start_mode}", f"    sta {self.next}",
                     "    jsr mode_transition"]

    def condition(self, condition, false_label):
        if not isinstance(condition, ModeActive):
            return None
        passed = self.compiler.unique("mode_active")
        return [f"    lda {self.current}", f"    cmp #{condition.mode.index}",
                f"    beq {passed}", f"    jmp {false_label}", f"{passed}:"]

    def action(self, action):
        if not isinstance(action, ChangeMode):
            return None
        if not any(action.mode is mode for mode in self.modes):
            raise ValueError("mode belongs to another game or was not registered")
        done = self.compiler.unique("mode_unchanged")
        code = [] if action.restart else [f"    lda {self.current}",
                                          f"    cmp #{action.mode.index}", f"    beq {done}"]
        return code + [f"    lda #{action.mode.index}", f"    sta {self.next}",
                       "    lda #1", f"    sta {self.pending}", "    rts", f"{done}:"]

    def scope(self, scope, false_label):
        if scope == "always":
            return []
        if scope is None or scope == "gameplay":
            passed = self.compiler.unique("mode_gameplay")
            return [f"    lda {self.gameplay}", f"    bne {passed}",
                    f"    jmp {false_label}", f"{passed}:"]
        return self.condition(ModeActive(scope), false_label)

    def routines(self):
        c = self.compiler
        code = [".export mode_transition", "mode_transition:", f"    lda {self.next}",
                f"    sta {self.current}", "    lda #0", f"    sta {self.pending}",
                *c.effects.begin_frame]
        for mode in self.modes:
            following = c.unique("mode_entry_next")
            code += [f"    lda {self.current}", f"    cmp #{mode.index}", f"    bne {following}",
                     f"    lda #{int(mode.gameplay)}", f"    sta {self.gameplay}",
                     f"    lda #{int(mode.pause_music)}", f"    sta {self.pause_music}",
                     f"    jmp mode_enter_{mode.index}", f"{following}:"]
        code += ["    rts"]
        for mode in self.modes:
            code += c.events(mode.enter_events, f"mode_enter_{mode.index}", scoped=False)
        return code
