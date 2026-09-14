# TEM-FLOW desktop and editable source

This folder is the editable application. It includes its Python runtime and does not require a repository connection or internet connection. It contains a private local server and a browser interface. On Windows with Microsoft Edge, the launcher opens a separate application window; otherwise it opens your default browser. The numerical engine runs on your PC.

1. Extract the complete desktop ZIP to a writable folder. Keep its folders together.
2. Double-click **Launch TEM-FLOW.vbs** (silent launcher), or **Launch TEM-FLOW.cmd**.
3. Optionally double-click **Create desktop shortcut.vbs** to place a launcher on your Windows desktop.
4. Use **Add new feature** above the map to add a node or a directed route. Repeat to add more nodes and routes. Each route needs two different active nodes. You can select two nodes on the map with Ctrl + double-click before opening Add route.
5. Use **Remove features** for one or multiple nodes/routes. Review the affected list. Removing a node requires explicitly including its connected routes. **Restore features** reverses a removal from a chosen date. Earlier views and the original input ledgers are preserved.
6. Close the window when finished. **Stop TEM-FLOW.cmd** stops the local engine; **Restart TEM-FLOW.cmd** loads saved code changes. Closing the window alone keeps the engine available.

The launcher detects changes to Python, interface and bundled data files. Launching again after editing restarts this application's own server gracefully. It does not terminate unrelated programs occupying other ports. The usual port is 8780; the launcher chooses another free local port when necessary.

## Where your data are saved

`user_data/` holds your added nodes/routes, revisions, removal/restoration history, settings and logs. Keep a backup of this folder. It is excluded from repository and release archives. To upgrade, stop the old application, extract the new version to a separate folder, then copy your `user_data/` into that new folder before launching it. Preserve the old folder as a rollback.

The desktop launcher generates a private curator token on first launch and signs the local owner into that session. A plain URL opened elsewhere has read access but no editing rights. Optional reader and curator tokens can be configured in `user_data/desktop_settings.json`. Never upload that file. No global Windows settings or administrator rights are needed.

The public desktop build contains the general engine and public map data. It does not contain the private Nature Food chemistry application ledger. Optional CPC, chemistry and exposure inputs can be loaded through the existing private-file controls.

## Editing and checking the source

Double-click **Edit source.cmd** to open the Python source folder. Use any text editor you are comfortable with. The map interface is `src/temflow/data/patterns_private_ui.html`. See **DEVELOPER_GUIDE.md** for the code map and a complete edit → test → version → release workflow.

After editing, double-click **Run checks.cmd**. Then use **Restart TEM-FLOW.cmd** to see your changes. Ordinary Python, HTML, CSS or JavaScript edits require no compilation. Changes requiring additional Python dependencies need a rebuilt runtime.

If launch fails, read `desktop-launch-error.log` or `user_data/desktop-server.log`. Do not run directly inside the ZIP archive.
