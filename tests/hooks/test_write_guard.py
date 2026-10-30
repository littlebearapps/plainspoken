import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HOOK = REPO / "hooks" / "write_guard.py"
CLAIMS_REPLY = ".plainspoken/reports/netball-rosters-547ed482.claims-reply.json"
CHECK_REPLY = ".plainspoken/reports/post-1234abcd.reply.json"
DELIVERY_REPLY = ".plainspoken/reports/post-1234abcd.delivery-reply.json"
LEDGER = ".plainspoken/claims/post-1234abcd.claims.toml"
REPLY_JSON = '{"article_sha256": "sha256:ab", "result": "PASS", "findings": []}'


def run_guard(command, raw=None, cwd=None) -> dict:
    event = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command}}
    if cwd is not None:
        event["cwd"] = cwd
    payload = raw if raw is not None else json.dumps(event)
    r = subprocess.run([sys.executable, str(HOOK)], input=payload, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout) if r.stdout.strip() else {}


class WriteGuard(unittest.TestCase):
    def assertDenied(self, command, cwd=None):
        out = run_guard(command, cwd=cwd)
        self.assertEqual(out.get("hookSpecificOutput", {}).get("permissionDecision"), "deny", command)
        self.assertIn("Write", out["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertIn("To read one, use cat", out["hookSpecificOutput"]["permissionDecisionReason"])

    def assertAllowed(self, command, cwd=None):
        self.assertEqual(run_guard(command, cwd=cwd), {}, command)

    def test_the_eval_printf_is_refused(self):  # #44: the claims-checker reply written with printf
        self.assertDenied(f"mkdir -p .plainspoken/reports && printf '%s\\n' '{REPLY_JSON}' > {CLAIMS_REPLY}\n"
                          'R="python3 /p/lib/run.py"; A=a.md\n$R claims record $A --from ' + CLAIMS_REPLY)

    def test_every_reply_file_is_refused_through_the_shell(self):
        for path in (CLAIMS_REPLY, CHECK_REPLY, DELIVERY_REPLY):
            with self.subTest(path=path):
                self.assertDenied(f"echo '{REPLY_JSON}' > {path}")
                self.assertDenied(f"echo '{REPLY_JSON}' >> \"{path}\"")
                self.assertDenied(f"cat > {path} <<'EOF'\n{REPLY_JSON}\nEOF")
                self.assertDenied(f"printf '%s' '{REPLY_JSON}' | tee -a {path} >/dev/null")
                self.assertDenied(f"python3 -c \"open('{path}', 'w').write('{{}}')\"")
                self.assertDenied(f"bash -c \"printf x > {path}\"")
                self.assertDenied(f"cp /tmp/reply.json {path}")
                self.assertDenied(f"echo \"$(printf x > {path})\"")

    def test_a_variable_holding_the_path_is_followed(self):
        self.assertDenied(f"F={CLAIMS_REPLY}; printf '%s' '{REPLY_JSON}' > \"$F\"")
        self.assertDenied(f"export F=\"{CHECK_REPLY}\"\nprintf x > ${{F}}")

    def test_a_ledger_built_by_a_script_is_refused(self):  # #44: three runs set every binding judgement in a loop
        self.assertDenied(f"cat > \"$TMPDIR/build.py\" <<'EOF'\nL=\"{LEDGER}\"\nout=['same_subject = true']\n"
                          "open(L, 'w').write(chr(10).join(out))\nEOF\npython3 -I \"$TMPDIR/build.py\"")
        self.assertDenied(f"python3 - <<'EOF'\nopen('{LEDGER}', 'w').write('x')\nEOF")
        self.assertDenied(f"sed -i 's/= false/= true/' {LEDGER}")
        self.assertDenied(f"cp /tmp/ledger.toml {LEDGER}")

    def test_code_that_only_reads_a_ledger_or_reply_is_allowed(self):  # #57: a read was refused like a write
        self.assertAllowed(f"python3 -c \"import tomllib; print(tomllib.load(open('{LEDGER}', 'rb')))\"")
        self.assertAllowed(f"python3 -c \"import json; d = json.load(open('{CLAIMS_REPLY}')); print(len(d))\"")
        self.assertAllowed(f"python3 -c \"from pathlib import Path; print(Path('{LEDGER}').read_text()[:400])\"")
        self.assertAllowed(f"python3 - <<'EOF'\nimport tomllib\nd = tomllib.load(open('{LEDGER}', 'rb'))\n"
                           "print(sum(c.get('status') == 'verified' for c in d['claims']))\nEOF")
        self.assertAllowed(f"node -e \"console.log(require('fs').readFileSync('{CHECK_REPLY}', 'utf8'))\"")
        self.assertAllowed(f"bash -c \"cat {LEDGER} | grep -c same_subject\"")
        self.assertAllowed(f"git commit -F - <<'EOF'\nfix: rebuild {LEDGER}\nEOF")

    def test_code_that_writes_a_ledger_or_reply_is_refused(self):
        self.assertDenied(f"python3 -c \"open('{LEDGER}', mode='w').write('x')\"")
        self.assertDenied(f"python3 -c \"import pathlib; pathlib.Path('{LEDGER}').write_text('x')\"")
        self.assertDenied(f"python3 -c \"import json; json.dump({{}}, open('{CHECK_REPLY}', 'a'))\"")
        self.assertDenied(f"python3 -Ic \"import os; os.system('printf x > {LEDGER}')\"")
        self.assertDenied(f"python3 - <<'EOF'\nimport re\nL = '{LEDGER}'\nt = open(L).read()\n"
                          "with open(L, 'w') as f:\n    f.write(re.sub('= false', '= true', t))\nEOF")
        self.assertDenied(f"python3 <<< \"open('{LEDGER}', 'w').write('x')\"")
        self.assertDenied(f"node -e \"require('fs').writeFileSync('{CHECK_REPLY}', '{{}}')\"")
        self.assertDenied(f"bash -lc 'L={LEDGER}; printf x > \"$L\"'")
        self.assertDenied(f"bash <<'EOF'\nprintf x > {LEDGER}\nEOF")
        self.assertDenied(f"perl -pi -e 's/false/true/' {LEDGER}")

    def test_a_script_run_by_name_is_read(self):  # #57: a script written earlier, then run without naming the file
        with tempfile.TemporaryDirectory() as d:
            files = {
                "build_ledger.py": f"L = '{LEDGER}'\nout = ['same_subject = true']\n"
                                   "open(L, 'w').write('\\n'.join(out))\n",
                "build_reply.js": f"require('fs').writeFileSync('{CLAIMS_REPLY}', '{{}}')\n",
                "fill.sh": f"#!/bin/sh\nL={LEDGER}\nsed 's/false/true/' \"$L\" > /tmp/l && cp /tmp/l \"$L\"\n",
                "outer.sh": "python3 build_ledger.py\n",
                "count.py": f"import tomllib\nprint(len(tomllib.load(open('{LEDGER}', 'rb'))['claims']))\n",
                "show.sh": f"cat {LEDGER}\n",
                "unrelated.py": "open('notes.txt', 'w').write('x')\n",
            }
            for name, text in files.items():
                Path(d, name).write_text(text, encoding="utf-8")
            os.chmod(Path(d, "build_ledger.py"), 0o755)
            for command in ("python3 build_ledger.py", f"python3 -u {d}/build_ledger.py", "./build_ledger.py",
                            "python3 < build_ledger.py", "node build_reply.js", "bash fill.sh", "sh -e ./fill.sh",
                            "bash outer.sh", f"cd drafts && python3 {d}/build_ledger.py || true"):
                with self.subTest(command=command):
                    self.assertDenied(command, cwd=d)
            for command in ("python3 count.py", "bash show.sh", "python3 unrelated.py", "python3 missing.py",
                            "python3 -m json.tool notes.json"):
                with self.subTest(command=command):
                    self.assertAllowed(command, cwd=d)

    def test_plainspokens_own_scripts_are_not_read(self):  # its tests name and write ledgers
        self.assertAllowed("python3 tests/hooks/test_write_guard.py", cwd=str(REPO))
        self.assertAllowed(f"python3 {REPO}/tests/test_cli_claims.py -k scaffold")

    def test_a_program_the_guard_cant_see_is_refused_when_the_command_names_the_file(self):  # fails safe
        with tempfile.TemporaryDirectory() as d:
            self.assertDenied(f"python3 missing.py {LEDGER}", cwd=d)
            self.assertDenied(f"python3 -m some_tool {LEDGER}", cwd=d)

    def test_a_chain_of_claims_calls_is_read_call_by_call(self):  # #78: claims/references/claude-code.md allows && chains
        run = "python3 /p/lib/run.py"
        pins = " && ".join(f"{run} claims pin --source .plainspoken/sources/brief.md --passage '{p}' --article a.md"
                           for p in ("We print a sheet.", "It'\\''s $1,000 && more > x.claims.toml", "Run build.py."))
        self.assertAllowed(pins)
        self.assertAllowed(f"{run} claims stamp a.md && {run} claims validate {LEDGER} && {run} claims recheck {LEDGER}")
        self.assertDenied(f"{pins} && printf x > {LEDGER}")
        self.assertDenied(f"{run} claims gaps a.md && sed -i 's/false/true/' {LEDGER} && {run} claims stamp a.md")

    def test_a_chain_of_reader_value_calls_is_read_call_by_call(self):  # #92: reader-value allows && chains too
        run = "python3 /p/lib/run.py"
        contract = "'.plainspoken/reader-value/a.reader-value.toml'"
        step3 = f"{run} paths 'a.md' && {run} reader-value deliver-input 'a.md' --contract {contract}"
        self.assertAllowed(step3)
        self.assertDenied(f"{step3} && printf '%s' '{REPLY_JSON}' > {DELIVERY_REPLY}")
        self.assertDenied(f"{run} paths 'a.md' && echo '{REPLY_JSON}' | tee {DELIVERY_REPLY} && "
                          f"{run} reader-value deliver 'a.md' --from {DELIVERY_REPLY} --reviewer delivery-checker")

    def test_a_literal_assigned_earlier_in_the_command_is_expanded(self):  # #161: python3 $R read as unseen
        self.assertAllowed(f"R=/x/lib/run.py; L='{LEDGER}'; python3 $R claims validate \"$L\"")
        self.assertAllowed(f"R=\"/x/lib/run.py\"\nL={LEDGER}\npython3 \"${{R}}\" claims gaps a.md && "
                           f"python3 $R claims validate \"$L\"")
        self.assertAllowed(f"export R=/x/lib/run.py && echo \"$(python3 $R claims validate {LEDGER})\"")
        with tempfile.TemporaryDirectory() as d:
            Path(d, "build.py").write_text(f"open('{LEDGER}', 'w').write('x')\n", encoding="utf-8")
            Path(d, "count.py").write_text(f"print(open('{LEDGER}').read())\n", encoding="utf-8")
            self.assertDenied(f"S=build.py; L='{LEDGER}'; python3 $S \"$L\"", cwd=d)
            self.assertDenied("S=./build.py; python3 \"$S\"", cwd=d)  # read now, so its write is seen
            self.assertAllowed(f"S=count.py; L='{LEDGER}'; python3 $S \"$L\"", cwd=d)

    def test_an_assignment_the_guard_cant_read_stays_unseen(self):  # #161: fails closed
        for setup in ("R=$(command -v run.py)", "R=`which run.py`", "R=\"$HOME/lib/run.py\"", "R=${P}/run.py",
                      "R='/x/lib/*.py'", "R=/x/lib/run.py | cat", "(R=/x/lib/run.py)", "false || R=/x/lib/run.py",
                      "R=/x/lib/run.py; unset R", "R=/x/lib/run.py; R=$(mktemp)", "R=/x/lib/run.py; read R",
                      "R=/x/lib/run.py & true"):
            with self.subTest(setup=setup):
                self.assertDenied(f"{setup}; L='{LEDGER}'; python3 $R claims validate \"$L\"")
        self.assertDenied(f"R=/x/lib/run.py python3 $R claims validate {LEDGER}")  # $R expands before R= applies
        self.assertDenied(f"R=/x/lib/run.py; bash -c 'python3 $R claims validate {LEDGER}'")  # not exported to it

    def test_an_unparseable_command_naming_a_reply_is_refused(self):
        self.assertDenied(f"printf '{{ > {CLAIMS_REPLY}")

    def test_the_cli_and_reads_are_allowed(self):
        self.assertAllowed(f"python3 /p/lib/run.py claims record \"drafts/a b.md\" --from {CLAIMS_REPLY}")
        self.assertAllowed(f'R="python3 /p/lib/run.py"; $R judge-record a.md --all --from {CHECK_REPLY} && '
                           "$R merge a.md --plugin-profile 'default'")
        self.assertAllowed(f"python3 -m plainspoken reader-value deliver a.md --from {DELIVERY_REPLY} "
                           "--reviewer delivery-checker")
        self.assertAllowed(f"python3 /p/lib/run.py claims scaffold a.md --out {LEDGER}")
        self.assertAllowed(f"cat {LEDGER}")
        self.assertAllowed(f"git add {LEDGER} && git commit -m ledger")
        self.assertAllowed(f"rm -f {CHECK_REPLY}")
        self.assertAllowed(f"cp {LEDGER} /tmp/ledger-backup.toml")
        self.assertAllowed(f"ls .plainspoken/reports/*.claims-reply.json 2>/dev/null")

    def test_other_commands_are_left_alone(self):
        self.assertAllowed("printf '{}' > out.json")
        self.assertAllowed("git push")
        self.assertAllowed("echo 'unbalanced")
        self.assertEqual(run_guard(None, raw="not json"), {})
        self.assertEqual(run_guard(None, raw=json.dumps({"tool_input": {"command": 3}})), {})

    def test_registered_on_bash_beside_the_publish_gate(self):
        cfg = json.loads((REPO / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
        pre = cfg["PreToolUse"][0]
        self.assertEqual(pre["matcher"], "Bash")
        guard = [h for h in pre["hooks"] if h["args"][0].endswith("/hooks/write_guard.py")]
        self.assertEqual(len(guard), 1)
        self.assertNotIn("onFailure", guard[0])  # runs on every Bash call: a failed start must not block them all
        self.assertNotIn("if", guard[0])


if __name__ == "__main__":
    unittest.main()
