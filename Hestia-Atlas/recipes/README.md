# Atlas site recipes

One JSON file per recipe (shape and ops: `app/recipes.py` docstring). Recipes are code: change them with a PR
(Forge fixes them when Argus reports `event=atlas_recipe_broken`). Test a recipe with
`POST /api/recipes/<name>/run` `{"params": {...}}` or the assistant tool `atlas_ricetta`.

| Recipe | Site | Params | Fields |
|---|---|---|---|
| `duckduckgo` | html.duckduckgo.com | `q` | titles, links, snippets |
| `pagina` | any | `url` | title, description, headings, text |
