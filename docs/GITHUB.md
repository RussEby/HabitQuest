# Publishing Habit Quest to GitHub

Everything below is one-time setup on this machine. After it, publishing a new
feature is just `git push` — including from an AI session.

## Where this repository stands

| | |
|---|---|
| Local repository | **yes** — `git rev-parse --is-inside-work-tree` reports `true` |
| Branch | `main` |
| Remote | **none yet** (`git remote -v` is empty) |
| Git | 2.56, with `credential.helper=manager` (Windows Credential Manager) |
| GitHub CLI | not installed |

The working tree is already cleaned: saves, build output, `node_modules`, the
`.freebuff/` folder and patch leftovers are ignored, so only source, tests and
docs are committable.

## 1. Create the repository on GitHub

Make an **empty** repository — no README, no `.gitignore`, no licence. Those
files already exist here, and a pre-filled repo makes the first push fail with
"updates were rejected".

Note the URL: `https://github.com/<your-name>/<repo-name>.git`.

## 2. Point this folder at it

```bash
git remote add origin https://github.com/<your-name>/<repo-name>.git
git remote -v
```

If you ever need to change it: `git remote set-url origin <new-url>`.

## 3. Sign in once, so pushes work without prompts

Pick **one** of these. The goal is the same in every case: a credential that
Windows Credential Manager can hand to `git` later, without a token living in
the repository or in this chat.

### Option A — the built-in credential manager (nothing to install)

`credential.helper=manager` is already set on this machine, so the first push
in step 4 is the whole setup: Git Credential Manager opens a browser window,
you sign in to GitHub and approve, and the credential is stored for every later
push. If no window appears (a headless or locked-down session), use one of the
options below instead.

### Option B — GitHub CLI

Install this if you would rather sign in from the terminal and get a helper
that also creates repositories, checks PRs and refreshes tokens.

```powershell
winget install --id GitHub.cli
```

Open a new terminal, then:

```powershell
gh auth login          # GitHub.com → HTTPS → Login with a web browser
gh auth setup-git      # makes sure git uses the CLI's credentials
```

Sign in through the browser. Nothing secret is typed into the shell.

### Option C — Personal access token

1. GitHub → **Settings → Developer settings → Personal access tokens →
   Fine-grained tokens → Generate new token**.
2. **Repository access:** only this repository.
3. **Permissions:** *Contents* = **Read and write**. *Metadata* = Read-only is
   added automatically. Nothing else is needed.
4. Set an expiry (90 days is sensible; you can rotate it later).

Then push once and let Git prompt you:

```bash
git push -u origin main
# Username: <your GitHub username>
# Password: paste the token — characters will not appear
```

Windows Credential Manager stores it after that first success, so the token is
never written to a file or to shell history. Do **not** paste the token into the
AI chat or put it in a command line; the prompt is the safe path.

### Option D — SSH key

```bash
ssh-keygen -t ed25519 -C "you@example.com"
cat ~/.ssh/id_ed25519.pub      # add this at GitHub → Settings → SSH and GPG keys
ssh -T git@github.com          # should greet you by name
git remote set-url origin git@github.com:<your-name>/<repo-name>.git
```

## 4. Push

```bash
git push -u origin main
```

`-u` records the upstream, so afterwards `git push` alone is enough.

If GitHub complains that the remote already has commits (because the repo was
created with a README), pull first and push again:

```bash
git pull --rebase origin main
git push -u origin main
```

## 5. Check what was actually published

```bash
git ls-remote --heads origin        # origin/main should appear
git status                          # "Your branch is up to date with 'origin/main'"
```

On the GitHub **Files** tab you should see `app.py`, `habitquest/`, `static/`,
`tests/`, `docs/`, `scripts/`, `desktop/` and **none** of:

- `habitquest.db*` or any `*.db` — your save file, and other people's saves
- `desktop/node_modules/` (≈455 MB), `desktop/release/` (≈806 MB),
  `desktop/backend-dist/`, `desktop/release-bundle/`
- `build/`, `dist/`, `__pycache__/`, `*.pyc`
- `.freebuff/`, `.vscode/`, editor swap files
- `*.log`, `*.orig`, `*.fixed`, `*.bak`, `*.patch`, `scratch-*`

## Letting the AI push after future features

Once step 3 has succeeded once, the credential lives in Windows Credential
Manager and the AI's `git` commands use it automatically — no token in the repo,
no token in the conversation.

The routine for each feature is:

```bash
git status                    # see what changed
git diff                      # review it
python -m unittest discover -s tests -t .
git add <specific files>      # avoid broad staging
git commit -m "…"
git push
```

Tell the AI "commit and push" when you want it to publish; it will not push on
its own otherwise. Useful guard rails to keep in mind:

- Keep the token scoped to **this repository** with **Contents: write** only.
  A leaked token then cannot touch anything else.
- If a push fails with `403` or `Authentication failed`, the token has expired —
  repeat `gh auth login`, or generate a new token and push once (Option C).
- Revoke a token at **Settings → Developer settings → Personal access tokens**
  the moment you think it has been exposed; then re-authenticate.
- Never commit `.env` files, keys or save files. The ignore rules above already
  cover the common cases, but `git status` before `git add` is the final check.

## Optional: make commits show your GitHub identity

This machine commits as `russe <russe@localhost>`, which GitHub will publish but
will not link to your profile. If you want the green contribution squares and
avatars, set the address GitHub gives you (find it under
**Settings → Emails → Keep my email addresses private**):

```bash
git config user.email "<ID>+<username>@users.noreply.github.com"
```

This only affects future commits; earlier ones keep the old address.
