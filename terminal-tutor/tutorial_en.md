# 🚀 TERMINAL BASICS & PRODUCTIVITY GUIDE

Welcome! This guide is for people who are seeing a terminal for the first time. A terminal is simply a text-based command window. You don't click; you type commands and press **Enter**.

Everything here is configured to make your life easier. Don't be afraid to try things out!

---

## ⌨️ 0. THE MOST IMPORTANT KEYS

Learn these first, they are your survival tools:

* **Enter** = Run the typed command
* **Tab** = Autocomplete (starts typing a folder/file? Press Tab to finish it!)
* **↑ / ↓** = Cycle through your previous commands
* **Ctrl + C** = 🛑 STOP! (Cancels whatever is currently running)
* **Ctrl + L** = 🧹 Clear the screen
* **q** = Quit (leaves most text viewers)
* **exit** = Close the terminal

---

## 🧭 1. MOVING AROUND (NAVIGATION)

You need to know where you are and how to move between folders.

* `pwd` = Print Working Directory (Shows where you are right now)
* `ls` = List files and folders in your current location
* `cd folder_name` = Enter a folder

**Jumping Backwards (The Dot Shortcuts):**
Normally, to go up you type `cd ..`. We made this much faster. Just type dots!

| Command | What it does | Example |
| :--- | :--- | :--- |
| `..` | Go **1** level up | `cd ..` |
| `...` | Go **2** levels up | `cd ...` |
| `....` | Go **3** levels up | `cd ....` |
| `.....` | Go **4** levels up | `cd .....` |

> 💡 **Tip:** If you are lost, just type `cd ~` to instantly go back to your Home folder!

---

## 📄 2. MANAGING FILES & EDITING

* `mkdir name` = Create a new folder
* `touch file.txt` = Create an empty file
* `rm file.txt` = Delete a file (⚠️ **Careful! There is no Recycle Bin!**)
* `cat file.txt` = Print the whole file to the screen
* `less file.txt` = Open the file in a scrollable viewer (Press `q` to quit)

**Editing files (Nano):**
Typing `nano file.txt` opens the default, beginner-friendly text editor. 
* Just start typing. 
* To save and exit: Press **Ctrl+X**, then **Y** (Yes), then **Enter**.

---

## 🔧 3. MODERN POWER COMMANDS (ALIASES)

We have replaced old, clunky commands with beautiful modern alternatives.

* 📊 **System Monitor (`btop`)**
  * *Instead of:* `top` or `htop`
  * *Just type:* `top` 
  * *What it does:* Opens a beautiful, interactive monitor showing CPU, RAM, and network usage. Press `q` to quit.
* 📖 **Quick Help (`tldr`)**
  * *Instead of:* reading 50 pages of `man` manuals.
  * *Just type:* `help <command>` (e.g., `help tar`)
  * *What it does:* Shows practical, short examples of how to use a command.
* 🎨 **Format JSON (`jq`)**
  * *Just type:* `cat data.json | json`
  * *What it does:* Takes ugly, unreadable JSON and makes it beautifully colored and indented.
* 🔎 **Search inside PDFs & Docs (`rga`)**
  * *Just type:* `rpdf "keyword" ~/Documents/`
  * *What it does:* Searches for text *inside* PDFs, Word docs, and archives, not just plain text files!

---

## ⚡ 4. THE ULTIMATE SHORTCUTS

### 🔍 FZF (Fuzzy File Finder)
Browsing folders manually is slow. 
* **Press `Ctrl + T`** anywhere in the terminal.
* Start typing any part of a filename. It filters instantly!
* A live preview of the file will appear on the right side.
* Press **Enter** to paste the file path directly into your command line.
* *(Bonus: Press **Ctrl + R** to quickly search your past commands!)*

### 📁 Midnight Commander (`mc`)
Love classic two-panel file managers? 
* **Type:** `mc`
* Use arrows to move, **Tab** to switch sides, and **F10** to quit.
* *Magic feature:* When you quit, your terminal will stay in the folder you were browsing, instead of throwing you back to where you started!

---

## 🆘 5. "COMMAND NOT FOUND" ERROR?

If you type a command that isn't installed (e.g., `cmatrix`), the terminal won't just give you a stupid error. It will automatically search the repositories and tell you exactly how to install it!

```text
$ cmatrix
cmatrix may be found in the following packages:
  extra/cmatrix 2.0-3

```

Just run `sudo pacman -S cmatrix` and you are good to go. No guessing required!

```
