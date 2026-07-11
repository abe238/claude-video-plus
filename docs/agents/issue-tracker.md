# Issue tracker: GitHub

Issues and PRDs for this repository live as GitHub issues in `abe238/claude-video-plus`. Use the `gh` CLI for all operations.

## Conventions

- Create: `gh issue create --title "..." --body "..."`. Use a body file for multiline content.
- Read: `gh issue view <number> --comments` and include labels.
- List: `gh issue list --state open --json number,title,body,labels,comments` with appropriate label and state filters.
- Comment: `gh issue comment <number> --body "..."`.
- Label: `gh issue edit <number> --add-label "..."` or `--remove-label "..."`.
- Close: `gh issue close <number> --comment "..."`.

Infer the repository from `git remote -v`; `gh` does this automatically inside the clone.

When a skill says to publish to the issue tracker, create a GitHub issue. When it says to fetch a ticket, use `gh issue view <number> --comments`.
