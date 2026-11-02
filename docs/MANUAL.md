# Drivion manual and demo guide

This guide covers everything Drivion can do, then gives you a script for recording a demo.

- [Part 1: Before you record](#part-1-before-you-record)
- [Part 2: Demo script](#part-2-demo-script)
- [Part 3: Everything Drivion can do](#part-3-everything-drivion-can-do)
- [Part 4: If something goes wrong on camera](#part-4-if-something-goes-wrong-on-camera)
- [Part 5: What's been tested](#part-5-whats-been-tested)

## Part 1: Before you record

### Protect your private details

The video will be public, so check these before you press record:

- [ ] **Keep `.env` closed.** It holds your API keys. If a key appears on screen, replace that
      key with your provider.
- [ ] **Don't open `drivion.log` on camera.** It contains the text of everything you've said to
      Drivion.
- [ ] **Show the settings screen's AI tab only with empty key boxes.** Never paste a key while
      recording.
- [ ] **Skip face enrollment on camera** unless you're happy to show that step. Your stored
      templates are safe, but your camera preview would be public.
- [ ] Close email, chats and banking tabs. Turn on **Do not disturb** so no notification appears.
- [ ] Clear personal names from your browser's start page and your desktop.

### Set up the computer

- [ ] Use a quiet room. Background talk can be heard as a command.
- [ ] Keep your speakers at a moderate level, so Drivion doesn't hear its own voice.
- [ ] Face a window or lamp. Even light on your face helps the check.
- [ ] Add Spotify or YouTube if you want to show media controls, and have something ready to play.
- [ ] Open your screen recorder, and capture **system audio and your microphone** so viewers
      hear both you and Drivion. OBS Studio does this well.
- [ ] Record a 10-second test and play it back.

### Start Drivion

```powershell
cd "C:\Users\MSI GF63\Desktop\Pet projects\Drivion"
.\.venv\Scripts\Activate.ps1
drivion --doctor
drivion --self-test
drivion
```

`--doctor` and `--self-test` should end with *"Everything Drivion needs is in place."* Then look
for the blue icon under the `^` arrow on the taskbar.

Run through Part 2 once without recording. Your first take will go better after a rehearsal.

### How to speak to Drivion

- Pause briefly, then speak one command at a time.
- Wait for Drivion to finish talking. It ignores the microphone while it speaks.
- Say **"Hey Drivion"** on its own, then stop.
- During head turns, turn clearly and hold for a moment. When it says *"Now look straight at the
  camera"*, look back before expecting the next prompt.

## Part 2: Demo script

This runs for about 8 minutes. Each scene stands alone, so you can record them separately and
join them. You can drop any scene to shorten it. The narration is a suggestion.

### Scene 1: Introduction (30 seconds)

*Show:* your normal desktop, with the tray icon visible.

> "This is Drivion, a personal AI assistant for Windows that I built. It's running right now, but
> there's no window. It's in standby, waiting for me. Watch what happens when I call it."

### Scene 2: Waking up safely (45 seconds)

*Say:* **"Hey Drivion"**

*Expect:* the tray icon turns amber, the camera turns on, and Drivion gives two head-turn prompts.
Follow them. It then says *"I'm listening"* and the dashboard opens.

> "It didn't just hear me. It checked my face, then asked for random head turns, so a photo of me
> can't unlock it. All of that happens on this computer."

### Scene 3: Keep it listening (15 seconds)

*Say:* **"Stay awake"**

*Expect:* *"Okay, I'll keep listening."* The dashboard minimizes, leaving your desktop clear.

> "Normally it goes back to standby after 20 seconds of silence. In this mode it stays with me
> while I work."

Do this scene early, so Drivion doesn't go to standby in the middle of a scene.

### Scene 4: Controlling the computer (1 minute)

Say these one at a time:

1. **"Set the volume to 40 percent"**
2. **"Turn the brightness down"**
3. **"Take a screenshot"**
4. **"Turn on dark mode"**, then **"Turn on light mode"**

> "It checks that each change really happened before it says it's done."

### Scene 5: Opening anything (1 minute)

1. **"Open the start menu"**, then say it again to close it
2. **"Open Spotify"**, or any app you have
3. **"Open bluetooth settings"**
4. **"Go to YouTube"**
5. **"Open my downloads folder"**

> "It can open any app in my Start menu, but it skips things like uninstallers."

### Scene 6: Windows and apps (1 minute)

1. **"Minimize Spotify"**
2. **"Snap this to the left"**
3. **"Switch to Chrome"**
4. **"Snap this to the right"**
5. **"Close Spotify"**
6. **"Show the desktop"**

### Scene 7: Writing by voice (1 minute 30 seconds)

1. **"Open notepad"**
2. **"Type Hello everyone, this was written by voice."**
3. **"Press enter"**
4. **"Type Drivion can edit too."**
5. **"Select all"**, then **"Copy"**
6. **"Undo"**, if you want to show it

> "That's real typing, with no keyboard. For safety, it won't type in a terminal, so nobody can
> use it to run commands."

To show that safety rule, say **"Open terminal"**, then **"Type dir"**. Drivion refuses. Then
say **"Close this window"**.

### Scene 8: Browsing (1 minute)

1. **"Open Chrome"**
2. **"New tab"**
3. **"Go to GitHub"**
4. **"Scroll down"**, then **"Scroll up"**
5. **"Go back"**
6. **"Close this tab"**

### Scene 9: Asking AI (45 seconds)

1. **"Who wrote Hamlet?"**
2. **"What's the capital of Japan?"**

> "Simple commands stay offline. Questions go to an AI, and if one provider fails, Drivion moves
> to the next."

### Scene 10: Safety (45 seconds)

*Say:* **"Shut down the computer"**

*Expect:* *"Are you sure you want me to shut down the computer? Say yes or no."*

*Say:* **"No"**

> "Anything serious needs a clear yes. If I stay silent or say anything else, nothing happens."

**Say "no" here, not "yes".** Saying yes really starts the shutdown.

### Scene 11: Ending (30 seconds)

*Say:* **"Drivion, go to sleep"**

*Expect:* the dashboard closes, and the tray icon turns blue again.

> "It's back to standby, with the camera off. This is Drivion."

## Part 3: Everything Drivion can do

You don't need these exact words, because filler like "please" and "can you" is ignored. Anything
Drivion can't match goes to the AI, which can only choose from its allowed actions.

### Waking and sleeping

| Say | What happens |
|---|---|
| "Hey Drivion" | Starts the face check |
| "Stay awake", "keep listening", "work mode" | Listens for up to 10 minutes of silence, and minimizes the dashboard |
| "Drivion, go to sleep", "that's all", "goodbye" | Returns to standby. Windows keeps running |

### Volume, brightness and display

| Say | What happens |
|---|---|
| "Set the volume to 40 percent", "volume 75" | Sets the level |
| "Louder", "quieter", "turn it up by 20" | Changes the level |
| "Mute", "unmute" | Mutes or unmutes |
| "Set the brightness to 70", "brighter", "dim the screen" | Built-in screens only |
| "Turn on dark mode", "switch to light mode" | Changes the Windows theme |

### Bluetooth, Wi-Fi and media

| Say | What happens |
|---|---|
| "Turn off bluetooth", "turn on bluetooth" | Changes Bluetooth and checks it |
| "Turn off wi-fi", "turn on wi-fi" | Changes Wi-Fi. AI answers stop while it's off |
| "Pause", "play", "next song", "previous song", "stop the music" | Works like your keyboard's media keys |

### Opening things

| Say | What happens |
|---|---|
| "Open Spotify", "launch Photoshop", "open task manager" | Opens an app from your Start menu |
| "Go to YouTube", "open my downloads folder" | Opens your allowlisted sites and folders |
| "Open settings", "open bluetooth settings" | Opens about 30 Settings pages, including Wi-Fi, display, sound, battery, storage, printers, wallpaper, privacy and Windows Update |
| "Open the start menu", "open search", "open notifications", "open quick settings", "open task view", "show the desktop" | Opens that part of Windows |

### Windows

"This" means the window you're using.

| Say | What happens |
|---|---|
| "Close Spotify", "close this" | Asks the app to close. It can still ask you to save |
| "Minimize this", "maximize Chrome", "restore Spotify" | Changes the window |
| "Switch to Chrome" | Brings it to the front |
| "Snap this left", "move Spotify to the right" | Moves it to half of the screen |

### Typing and keys

| Say | What happens |
|---|---|
| "Type hello team", "write dear John" | Types into the active window, up to 500 characters at a time |
| "Press enter", "press tab", "press escape", "press backspace" | Presses that key |
| "Save this", "copy", "paste", "cut", "undo", "redo", "select all", "find" | Presses the usual shortcut |
| "New tab", "close this tab", "next tab", "previous tab", "reopen tab" | Tab controls |
| "Go back", "go forward", "refresh", "address bar" | Browser controls |
| "Scroll down", "scroll up", "go to the top", "zoom in", "zoom out", "full screen" | Moves around the page |

### Everything else

| Say | What happens |
|---|---|
| "Take a screenshot" | Saves to `Pictures\Screenshots` |
| "Lock the computer" | Locks Windows, and Drivion returns to standby |
| "Put my computer to sleep", "restart the computer", "shut down the computer" | Asks you first. Say **yes** or **no** |
| "Cancel" | Stops a pending action, or a restart or shutdown during its 10-second delay |
| "Help", "repeat that" | Lists examples, or repeats the last reply |
| "Who wrote Hamlet?" | Asks the AI. Needs internet and a key |

### Dashboard and tray

- **Dashboard:** shows the state, microphone and camera status, conversation, and command history.
- **Tray icon:** blue is standby, amber is verifying, cyan is active, and red is an error.
- **Tray menu:** *Open Drivion*, *Settings*, *Exit Drivion* and *Recover from error*.
- **Settings:** voice, wake word, privacy and AI provider, only while unlocked. Changes apply
  after a restart. *Start Drivion when I sign in to Windows* is in the Privacy tab.

### Commands for PowerShell

| Command | What it does |
|---|---|
| `drivion --doctor` | Checks everything and prints the fixes |
| `drivion --self-test` | Runs every engine |
| `drivion --test-wake` | Listens for 30 seconds and shows what it hears |
| `drivion --enroll-face`, `--test-face`, `--test-liveness`, `--delete-face` | Face tools |
| `drivion --autostart on`, `off`, `status` | Start at login |
| `drivion --check-config` | Checks settings, and which AI keys are present |
| `drivion --simulate` | Adds a developer menu to the tray |

### Safety rules

| Rule | Why |
|---|---|
| Commands only run while unlocked | Nobody can use it without passing the face check |
| Sleep, restart and shut down need a clear yes | Silence or an unclear reply never counts |
| No typing or key presses in terminals, the Run box or Windows search | Drivion must never become a way to run commands |
| The AI can't type, press keys, close windows or open apps outside your list | Only your own words can do those |
| Closing is always a normal close | The app can ask you to save |
| No uninstallers, repair tools or admin shortcuts | Voice shouldn't change what's installed |
| App names are never guessed | If a name fits several apps, Drivion asks |

**Limits to know about:**

- Drivion can't see inside a window, so it can't click buttons by name yet.
- **It can't detect password boxes, so don't dictate passwords.** What you dictate is also
  written to the log.
- Its terminal check looks at the window, so it can't tell when you're in the terminal inside
  VS Code. Don't use "type" there.
- While it's active, it obeys any voice it hears. Say "go to sleep" before leaving your PC.
- If you lock Windows with Win+L rather than by voice, Drivion keeps listening until it times out.
- Admin windows ignore its keys.
- "Pause" and "play" are the same media key, so either one toggles playback.
- "Scroll" uses the page keys, so in a text editor it also moves the cursor.

## Part 4: If something goes wrong on camera

| What happens | What to do |
|---|---|
| Nothing happens after "Hey Drivion" | Pause, then say it again on its own. Or right-click the tray icon and choose *Open Drivion*. Off camera, `drivion --test-wake` shows what it hears |
| *"Access denied: the head turn wasn't seen in time"* | Turn further and hold for a moment, then try again |
| *"You didn't look back at the camera in time"* | Face the camera when told to, then try again |
| It went back to standby | Say "Hey Drivion". Say "stay awake" once you're in |
| It misheard an app's name | Repeat it slowly. The dashboard shows what it heard |
| *"I found A and B. Which one?"* | Say the full name |
| *"I can't tell which window you mean"* | Click the window, then say the command again |
| Keys went nowhere | Click the window you want first |
| The tray icon is red | Choose *Recover from error* in the tray |

Every scene can be cut and retaken, so don't stop for a small mistake. Pause for three seconds,
say the line again, and trim it later.

**Backup plan:** if the microphone or room noise won't cooperate, record `drivion --simulate`.
*Simulate → Wake word detected*, then *Face verified*, opens the dashboard without speaking. Say
in the video that you're using simulation.

## Part 5: What's been tested

Be honest about these in the video description if you make claims about reliability.

| Feature | Status |
|---|---|
| "Hey Drivion", face check, head turns | Worked with your real voice and face |
| Volume, brightness, opening a website | Worked with your real voice |
| AI answers through Gemini | Worked with your real key |
| Groq and OpenRouter | Keys detected, but never used in a real call |
| Installed apps, Settings pages, Start menu | Tested on your PC with typed commands |
| Closing, minimizing, maximizing, switching, snapping | Tested on your PC with Calculator |
| Typing, select all, backspace, enter | Tested on your PC in a test window |
| Refusing to type in a terminal | Tested on your PC in Windows Terminal |
| Turning Bluetooth or dark mode to the state they were already in | Tested on your PC |
| Actually switching Bluetooth, Wi-Fi or the theme | **Not tested yet. Rehearse these** |
| Media keys, search, notifications, quick settings, task view, show desktop | **Not tested on your PC yet. Rehearse these** |
| Any of the new commands by real voice | **Not tested yet. Rehearse these** |
| Long "stay awake" session | **Automated tests only. Rehearse this** |
