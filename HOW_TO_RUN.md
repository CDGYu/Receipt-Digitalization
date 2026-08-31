# How to run Receipt Review

This is the everyday guide for using the app. You do not need to know any code.

## Start it

**Double-click `Start Receipt Review.bat`** in this folder.

A black window opens and shows what it is doing. In a few moments your web
browser opens at the review screen. That is it.

Leave the black window open while you work. When you are finished, **close that
window** (or click it and press `Ctrl` + `C`). That stops the app cleanly.

> **The very first time on a computer takes longer.** It sets itself up -
> creating its own private environment and downloading the parts it needs - so
> the first launch needs an internet connection and may take a few minutes. You
> will see `[setup]` lines while it works. Every launch after that is quick and
> works offline.

## The first time only: create your sign-in

The very first time you run it, the window asks you to create an account:

```
No sign-in account exists yet. Let's create one now (one time only).
  Choose a username:
  Choose a password (typing is hidden):
  Type the password again to confirm:
```

Type a username and a password (the password will not show on screen as you
type - that is normal). You will use these to sign in from then on. It only
asks once; after that it goes straight to the app.

If you ever get locked out, see "Add another sign-in account" below.

## Moving to another computer

You can copy this whole folder to another Windows PC and run it there. Before
the first launch on the new machine, make sure of two things:

1. **Python 3.11 or newer is installed.** This is the one thing the app cannot
   install for you. Get it from <https://www.python.org/downloads/> and tick
   "Add Python to PATH" during setup. If it is missing, the launcher window
   tells you exactly this.
2. **You have internet for the first launch.** The first double-click downloads
   and installs the app's components into a private folder called `.venv` inside
   the project. After that first time it no longer needs the internet to start
   (though reading receipts with the cloud model still does).

Everything else travels with the folder and is handled automatically: the queue
(a small bundled Redis), the built website, and all the app components installed
on first launch.

**Optional:** if you want the app to use a *local* AI model instead of the cloud
one, install Ollama on the new machine (<https://ollama.com>) and pull the model
named in the settings. Without it, the app uses the cloud model configured in
`.env` - so a valid cloud key must be present there for reading to work.

Copying the folder is enough to bring your existing receipts and accounts along,
because they live in the project folder too. If you want a clean start on the
new machine, delete the `.db` file before the first launch and it will set up a
fresh database and ask you to create a new account.

## Using the app

1. Sign in with the username and password you created.
2. Upload a receipt photo (or several - single receipts or a whole batch both
   work).
3. The app reads each receipt. Ones it is confident about are approved
   automatically; ones it is unsure about are put in the review queue for you to
   check and correct.
4. When you want the results as a spreadsheet, use the export option to get an
   Excel file.

## What starts up (for the curious)

The launcher starts three things and then opens your browser:

- **the queue** (a small bundled Redis - nothing to install),
- **the worker** that actually reads the receipts,
- **the review website** you see in the browser.

Everything runs on this one computer. Nothing is exposed to the internet.

## The AI model

The app is set to use a local model first (Ollama on this machine) and fall
back to a cloud model if the local one is slow or unavailable. On startup the
window tells you whether the local model is ready. If it says something like:

```
WARNING: Ollama does not appear to be running ...
WARNING: VLM_MODEL_EXTRACT is 'granite3.2-vision:2b', which is not pulled ...
```

then either start the Ollama app, or the app will simply use the cloud fallback
if one is configured. A warning here does not stop the app.

## If something goes wrong

- **The window closes instantly.** Python may not be installed. Install
  Python 3.11 or newer from <https://www.python.org/downloads/> and tick
  "Add Python to PATH" during setup, then try again.
- **First-time setup fails ("Setup did not finish").** This almost always means
  no internet during the one-time install. Connect to the internet and run the
  file again. To force a clean setup, delete the `.venv` folder and try again.
- **The browser shows a connection error.** Give it a few more seconds and
  refresh. If it still fails, read the black window - the last lines say what
  did not start.
- **"Cannot continue without Redis."** Another program may be using the queue's
  port. Close other copies of this app and try again.
- **You uploaded a receipt and nothing happens.** Check the model warning above -
  the local model may not be pulled and no cloud fallback is set.

If you need to report a problem, copy the text from the black window - it is the
most useful thing to include.

## Add another sign-in account

To add more accounts (for example, if you are locked out or want a second
reviewer), open a terminal in this folder and run:

```
python -m receipts.cli users add SOMENAME
```

It asks for a password (hidden as you type). Use `--role admin` to make an
admin account. To see existing accounts: `python -m receipts.cli users list`.
