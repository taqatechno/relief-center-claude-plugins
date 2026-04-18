# relief-center-claude-plugins

A marketplace of [Claude Code](https://claude.com/claude-code) plugins that support Relief Center's Odoo CMS workflows.

## Plugins

| Plugin | What it does |
|---|---|
| [`publish-relief-center-news`](plugins/publish-relief-center-news/) | Publish unpublished bilingual (English + Arabic) news articles from a monthly news `.docx` into the Odoo **Latest News** blog, and recolor the published cells purple so the docx stays in sync. |

New plugins land under `plugins/<plugin-name>/` and get an entry added to `.claude-plugin/marketplace.json`.

## Install the marketplace

Add this repository as a marketplace in your Claude Code settings, then enable whichever plugins you want.

### From the local clone (dev path)

In your user-level `~/.claude/settings.json` or a project's `.claude/settings.json`:

```json
{
  "extraKnownMarketplaces": {
    "relief-center-claude-plugins": {
      "source": { "source": "directory", "path": "/absolute/path/to/relief-center-claude-plugins" }
    }
  },
  "enabledPlugins": {
    "publish-relief-center-news@relief-center-claude-plugins": true
  }
}
```

Replace the path with the absolute path to your clone. Claude Code re-reads settings on session start — restart the session to pick up the changes, or run `/plugin` to reload.

### From GitHub (once this repo is pushed)

```json
{
  "extraKnownMarketplaces": {
    "relief-center-claude-plugins": {
      "source": { "source": "github", "repo": "<your-org>/relief-center-claude-plugins" }
    }
  },
  "enabledPlugins": {
    "publish-relief-center-news@relief-center-claude-plugins": true
  }
}
```

## Per-plugin configuration

Each plugin declares its own userConfig fields. After enabling a plugin, run `/plugin config <plugin-name>` to fill them in. See each plugin's README for field descriptions.

## Repo layout

```
relief-center-claude-plugins/
├── .claude-plugin/
│   └── marketplace.json         # index of plugins in this repo
├── plugins/
│   └── publish-relief-center-news/
│       ├── .claude-plugin/
│       │   └── plugin.json      # plugin manifest + userConfig declaration
│       ├── skills/
│       │   └── publish-relief-center-news/
│       │       ├── SKILL.md
│       │       ├── references/
│       │       └── scripts/
│       └── README.md            # plugin-specific install/config/usage
├── README.md                    # you are here
├── LICENSE                      # MIT, shared across all plugins in this repo
└── .gitignore
```

## Adding a new plugin

1. Create `plugins/<plugin-name>/.claude-plugin/plugin.json` with the manifest (name, description, version, author, userConfig).
2. Add its skills/commands/agents/hooks under `plugins/<plugin-name>/`.
3. Add an entry to `.claude-plugin/marketplace.json` with `"source": "./plugins/<plugin-name>"`.
4. Write a plugin-specific `README.md`.

## License

MIT. See [`LICENSE`](LICENSE).
