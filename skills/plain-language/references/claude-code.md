# Claude Code specifics for plain-language

- The cold reader is the `plainspoken:cold-reader` subagent. Start one, with a prompt of exactly two lines:

  ```
  Reader: <the reader line>
  File: <absolute path>
  ```

  Take the reader line from the first step's profile and pass the path as an absolute one, so the agent doesn't
  depend on the working folder. Relay its flags in the report. If the agent isn't installed, read the text yourself
  as that person.
- `${user_config.profile}` may stay as the literal text when the plugin loads with `--plugin-dir`. The CLI treats the
  literal as the shipped default profile, so the skill still runs. See `docs/claude-code-facts.md`, section 3.
- Plugin options may not reach the shell the commands run in, so pass the profile on the command line
  (`--plugin-profile '${user_config.profile}'`). See `docs/claude-code-facts.md`, section 4.
- The skill triggers on its own when someone asks for easier or plainer text. It can run the CLI and edit the file you
  name when you use `--rewrite`; an audit changes nothing.
