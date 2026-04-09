# ReflistBot

A Python bot that fixes and standardizes "References" sections on MediaWiki pages using the API.

## What it does

- Logs into a wiki using bot credentials  
- Reads a worklist of pages  
- Fixes or inserts a `== References ==` section with `{{reflist}}`  
- Skips pages without `<ref>` tags  
- Marks completed pages as done  
- Updates the worklist timestamp

## GitHub Actions

This bot can run automatically using GitHub Actions.

Store your credentials as repository secrets:

- `BOT_USER`
- `BOT_PASS`

Then create a workflow file in `.github/workflows/run-bot.yml`.

## Setup

Install dependencies:

```bash
pip install requests
