# Presenter Notes — Anticipated Questions & Answers

---

## "What is macOS Keychain?"

Apple's built-in credential manager. Same thing that stores your Wi-Fi passwords, SSH keys, and browser certificates. It's encrypted with your login password and protected by the Secure Enclave on Apple Silicon. Every macOS app that handles credentials (Safari, Mail, SSH) uses it. We store the P4 password there so the MCP server can silently refresh tickets without asking you to log in.

---

## "Is storing my password in Keychain safe?"

Yes. Keychain is hardware-encrypted, locked behind your macOS login, and protected by the Secure Enclave chip. The password never touches disk in plaintext — no config files, no `.env`, no logs. It's the same mechanism Apple uses for iCloud Keychain, Touch ID credentials, and FileVault keys. It's significantly safer than having your password in a `.p4enviro` file or a shell profile.

---

## "What if I don't want to store my password?"

Skip it. The server falls back to SAML/SSO — it opens your browser automatically when the ticket expires. You complete the SSO page, the server picks up the new ticket, and continues. Zero copy-pasting. The Keychain option just removes even that browser step.

---

## "Is the Swarm API call safe? Can it break anything?"

The `raise_review` call does exactly what clicking "Request Review" in Swarm's web UI does — same endpoint (`POST /api/v9/reviews`), same auth. It can only shelve files in your own changelist and create a review owned by your P4 user. It cannot submit code, delete files, or touch anyone else's reviews.

---

## "What about the `verify=False` in the HTTP client?"

That disables TLS certificate verification for the internal Swarm server, which uses a self-signed certificate. This is standard for internal Cisco infrastructure. The traffic requires VPN to reach Swarm in the first place, so it never leaves the corporate network. If your Swarm server had a CA-signed cert, you'd remove that flag.

---

## "Does the AI see my password?"

No. The AI IDE calls the MCP tool, which runs as a separate process. The password lives in Keychain and is read by the Python server process at runtime — piped into `p4 login` and discarded. It never appears in the MCP protocol messages, the AI's context window, or any logs.

---

## "What is MCP? Why not just use the terminal?"

MCP (Model Context Protocol) is an open standard by Anthropic. It lets AI IDEs call external tools and get structured results back. Without it, you'd run a command in terminal, copy the output, paste it into chat, wait for analysis, copy the answer, go to Swarm, paste it. With MCP, the AI does all of that in one step — it calls the tool directly, gets the data, and acts on it.

---

## "Does this work with VS Code / Windsurf / other IDEs?"

Any IDE that supports MCP. Cursor has it built-in. VS Code has it via GitHub Copilot's MCP support. Windsurf supports it natively. The config file path changes per IDE, but the servers themselves are IDE-agnostic.

---

## "What happens if VPN drops mid-operation?"

The `p4` command fails, the server catches it, and returns a clear error: "Cannot reach Perforce server — check your VPN connection." Nothing is left in a partial state. Shelving is atomic — it either completes fully or not at all.

---

## "Can the AI submit my changelist (push to production)?"

No. The tools support shelving and creating reviews only. There is no `p4 submit` tool. Code can only be submitted through the normal review and approval process.

---

## "What's the difference between the two MCP servers?"

**perforce-p4** is the official Perforce MCP binary — good for read-only queries (file content, history, annotations, workspace info). **p4-workflow** is our custom server — handles the full workflow (create CL with Cisco template, shelve, raise Swarm review, fetch diffs, post comments). They run side by side. The AI picks the right one based on the task.

---

## "How does it know which workspace to use?"

You pass the branch name (e.g. `IMS_10_5_MAIN`). The server prepends your username to form the workspace name (`devseth_IMS_10_5_MAIN`). For operations on existing CLs, it reads the workspace from the CL spec using `p4 change -o` — fully automatic.

---

## "What if my ticket expires mid-session?"

Transparent recovery. The `p4` command fails, the server detects the auth error, tries Keychain login (instant), and retries the command. If Keychain isn't set up, it opens the browser for SSO, waits for completion, and retries. You see the result, not the retry.

---

## "What data does the server send to the AI?"

Only what the tool returns — CL descriptions, file diffs, review metadata, Swarm comments. No passwords, no tickets, no Keychain data. The MCP protocol separates tool execution (server-side) from AI reasoning (IDE-side).

---

## "How do I set it up?"

One command: `./setup.sh`. It installs everything from scratch — Homebrew, p4 CLI, Python, Node.js, dependencies, auth, MCP config, AI rules. Takes about 2 minutes. Restart the IDE, done.

---

## "Can someone else use my setup?"

The setup is per-user. Each person runs `./setup.sh` with their own P4USER, and their password goes into their own Keychain. No shared credentials.
