"""Tests for update_from_github.sh. Everything runs in temp repos with a fake gh;
the real repository, its remote and the real gh are never touched."""
import os
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT_SRC = os.path.join(ROOT, "update_from_github.sh")


def git(cwd, *args):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True,
                          capture_output=True, text=True).stdout


def prices(date):
    return 'window.FUEL_PRICES = {"date":"%s","n":1};\n' % date


def write(path, text):
    with open(path, "w") as f:
        f.write(text)


def read(path):
    with open(path) as f:
        return f.read()


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.origin = os.path.join(self.tmp, "origin.git")
        seed = os.path.join(self.tmp, "seed")
        self.clone = os.path.join(self.tmp, "clone")
        self.pusher = os.path.join(self.tmp, "pusher")
        git(self.tmp, "init", "--bare", "-b", "main", self.origin)
        git(self.tmp, "init", "-b", "main", seed)
        write(os.path.join(seed, "prices.js"), prices("2026-10-28"))
        write(os.path.join(seed, "fuel-calculator.html"), "<html>v1</html>\n")
        shutil.copy(SCRIPT_SRC, os.path.join(seed, "update_from_github.sh")) if os.path.exists(SCRIPT_SRC) else None
        git(seed, "add", ".")
        git(seed, "commit", "-m", "seed")
        git(seed, "remote", "add", "origin", self.origin)
        git(seed, "push", "origin", "main")
        git(self.tmp, "clone", self.origin, self.clone)
        git(self.tmp, "clone", self.origin, self.pusher)
        self.gh_log = os.path.join(self.tmp, "gh.log")
        self.gh = os.path.join(self.tmp, "gh")
        write(self.gh, '#!/bin/sh\necho "$@" >> "%s"\n[ -n "$FAKE_GH_ERR" ] && echo "$FAKE_GH_ERR" >&2\nexit ${FAKE_GH_EXIT:-0}\n' % self.gh_log)
        os.chmod(self.gh, 0o755)

    def push_new_prices(self, date="2026-10-29"):
        write(os.path.join(self.pusher, "prices.js"), prices(date))
        git(self.pusher, "commit", "-am", "prices " + date)
        git(self.pusher, "push", "origin", "main")

    def run_script(self, gh=None, **extra):
        env = dict(os.environ, FC_GH=self.gh if gh is None else gh,
                   FC_WAIT_SECONDS="0", FC_WAIT_ROUNDS="2", **extra)
        r = subprocess.run(["bash", os.path.join(self.clone, "update_from_github.sh")],
                           cwd=self.tmp, env=env, capture_output=True, text=True, timeout=60)
        return r, r.stdout + r.stderr

    def test_pulls_new_prices_over_local_change(self):
        self.push_new_prices()
        write(os.path.join(self.clone, "prices.js"), prices("1999-01-01"))
        r, out = self.run_script()
        self.assertEqual(r.returncode, 0, out)
        self.assertEqual(read(os.path.join(self.clone, "prices.js")), prices("2026-10-29"))
        self.assertEqual(git(self.clone, "status", "--porcelain"), "")

    def test_keeps_local_commit(self):
        write(os.path.join(self.clone, "notes.txt"), "mine\n")
        git(self.clone, "add", "notes.txt")
        git(self.clone, "commit", "-m", "local work")
        head = git(self.clone, "rev-parse", "HEAD")
        self.push_new_prices()
        r, out = self.run_script()
        self.assertEqual(r.returncode, 0, out)
        self.assertEqual(git(self.clone, "rev-parse", "HEAD"), head)
        self.assertIn("could not update", out.lower())

    def test_keeps_other_edits(self):
        self.push_new_prices()
        html = os.path.join(self.clone, "fuel-calculator.html")
        write(html, "<html>my edit</html>\n")
        r, out = self.run_script()
        self.assertEqual(r.returncode, 0, out)
        self.assertEqual(read(html), "<html>my edit</html>\n")
        self.assertEqual(read(os.path.join(self.clone, "prices.js")), prices("2026-10-29"))

    def test_skips_other_branch(self):
        git(self.clone, "checkout", "-b", "feature/x")
        write(os.path.join(self.clone, "fuel-calculator.html"), "<html>wip</html>\n")
        write(os.path.join(self.clone, "prices.js"), prices("1999-01-01"))
        self.push_new_prices()
        head = git(self.clone, "rev-parse", "HEAD")
        r, out = self.run_script()
        self.assertEqual(r.returncode, 0, out)
        self.assertEqual(git(self.clone, "rev-parse", "--abbrev-ref", "HEAD").strip(), "feature/x")
        self.assertEqual(git(self.clone, "rev-parse", "HEAD"), head)
        self.assertEqual(read(os.path.join(self.clone, "fuel-calculator.html")), "<html>wip</html>\n")
        self.assertEqual(read(os.path.join(self.clone, "prices.js")), prices("1999-01-01"))

    def test_missing_gh_still_pulls(self):
        self.push_new_prices()
        r, out = self.run_script(gh=os.path.join(self.tmp, "nope"))
        self.assertEqual(r.returncode, 0, out)
        self.assertEqual(read(os.path.join(self.clone, "prices.js")), prices("2026-10-29"))

    def test_failing_gh_still_pulls(self):
        self.push_new_prices()
        r, out = self.run_script(FAKE_GH_EXIT="1", FAKE_GH_ERR="keychain locked: no auth token found")
        self.assertEqual(r.returncode, 0, out)
        self.assertEqual(read(os.path.join(self.clone, "prices.js")), prices("2026-10-29"))
        self.assertRegex(out, r"(?i)gh.*fail")
        self.assertIn("keychain locked: no auth token found", out)

    def test_triggers_the_price_job(self):
        r, out = self.run_script()
        self.assertEqual(r.returncode, 0, out)
        self.assertEqual(read(self.gh_log).strip(), "workflow run update-prices.yml")

    def test_log_lines_are_timestamped(self):
        r, out = self.run_script()
        for line in out.strip().splitlines():
            self.assertRegex(line, r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}\] ")

    def test_not_a_repo_fails(self):
        d = os.path.join(self.tmp, "plain")
        os.mkdir(d)
        shutil.copy(SCRIPT_SRC, d)
        r = subprocess.run(["bash", os.path.join(d, "update_from_github.sh")],
                           env=dict(os.environ, FC_GH=self.gh, FC_WAIT_SECONDS="0"),
                           capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)


class ScheduleTests(unittest.TestCase):
    def test_syntax_and_times(self):
        path = os.path.join(ROOT, "schedule_prices.sh")
        subprocess.run(["bash", "-n", path], check=True)
        text = read(path)
        for day in range(1, 6):
            for hour, minute in ((10, 45), (12, 0), (15, 0)):
                self.assertIn(
                    "<key>Weekday</key><integer>%d</integer><key>Hour</key><integer>%d</integer>"
                    "<key>Minute</key><integer>%d</integer>" % (day, hour, minute), text)
        self.assertNotIn("<integer>30</integer>", text)
        self.assertIn("update_from_github.sh", text)
        self.assertIn("<string>/bin/bash</string>", text)


if __name__ == "__main__":
    unittest.main()
