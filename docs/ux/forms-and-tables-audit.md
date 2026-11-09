# BeeOne forms and tables UX audit

## Scope and shared architecture

BeeOne's Desk document and catalog forms use Frappe's metadata-driven form pipeline. A
doctype does not own a separate page implementation:

- `frappe/public/js/frappe/form/form.js` creates the page-level `Form` and its
  toolbar, sidebar, footer, dashboard and shared layout.
- `frappe/public/js/frappe/form/layout.js` turns DocType metadata into sections,
  columns and tabs. Create, edit and read-only states use this same layout.
- `frappe/public/js/frappe/form/controls/base_control.js` and
  `base_input.js` resolve field visibility, permissions, read-only state,
  mandatory state, validation and fetched values for the shared controls.
- `frappe/public/js/frappe/form/grid.js` and `grid_row.js` render every child
  table field. Grid pagination, column selection, resizing, ordering, width,
  visibility, sticky columns and horizontal scrolling are shared behavior.
- Catalog list pages use the separate `frappe/public/js/frappe/list/list_view.js`
  renderer. Its column layout and resizing are shared for all DocTypes; it is not
  the child-table Grid.
- `frappe/public/js/frappe/form/sidebar/form_sidebar.js` and
  `frappe/public/js/frappe/form/toolbar.js` provide the document information
  panel and its actions across forms. `frappe/public/js/frappe/ui/sidebar/sidebar.js`
  owns the main Desk navigation.

The newer Vue package in `ui/src/components/FormLayout` and `ui/src/components/Grid`
is an exported app component library. The classic Desk DocType forms inspected here
are rendered by the Frappe `form/` pipeline above, so the global form changes belong
there rather than in separate document implementations.

## Findings and changes

| Area | Audit finding | Shared change |
| --- | --- | --- |
| Table preferences | Child-table preferences were keyed by child DocType. Two fields using the same child DocType could overwrite each other's configuration; custom columns also mutated shared DocField metadata. | Store preferences by parent DocType plus table fieldname; clone DocField metadata for each grid; reset only that grid's preference. |
| Table setup | Grid already supported column visibility, order, resize, width and sticky columns, but there was no shared density control. | Added one saved density preference and a common control for document grids and catalog ListView tables. |
| Long cell values | Grid cells were clipped without a native full-value hint. ListView already provided value titles for ordinary fields. | Added a title to the Grid cell using its rendered value. Existing ListView title handling remains in place. |
| Form sidebar | The document panel had a menu action but no visible desktop toggle and did not retain a per-user setting. | Added a page action, accessible pressed state, and persisted preference. |
| Main navigation | The collapse/tooltip behavior already existed, but its browser storage key was shared by accounts and was not synced with the user. | Scope the local fallback by account and persist the expanded state in user settings. |
| Field states and spacing | Shared controls already handled write/read/required/error states. Auto-fetched values had a source tooltip but no marker; standard field gaps were larger than needed. | Add shared state classes, an auto-value marker and source hint, and reduce standard field/section spacing. |

The compact table mode reduces row padding and height while keeping text size unchanged.
Read-only document tables retain access to the density control while hiding row-edit
actions. No document-specific files, business rules, validations, posting logic or
permission checks were changed.

## Source-level scenario coverage

| Scenario | Shared path inspected | Live browser run |
| --- | --- | --- |
| New, editing and read-only document | `Form`, `Layout`, shared field controls and permission status | Not run |
| Many fields, sections and tabs | Metadata-driven `Layout` and field controls | Not run |
| Large child table | `Grid`, `GridRow`, pagination, column settings and horizontal scroll | Not run |
| Complex business document | Same `Form`/`Layout` path; business handlers remain outside this change | Not run |
| Large catalog list | `ListView` renderer and per-DocType list columns | Not run |
| Catalog with custom fields | DocType metadata through the same `Layout` and ListView paths | Not run |
| Narrow/mobile viewport | Existing mobile branches and responsive Desk styles; new controls remain in shared containers | Not run |

## Verification

- JavaScript parser checks passed for all changed JavaScript modules.
- An isolated runtime check passed for loading and toggling table density and for
  concurrent per-user preference saves.
- Babel parsed `frappe/locale/uk.po` successfully (6,601 messages).
- `git diff --check` passed.
- The frontend build and browser scenarios could not be run in this checkout: no
  Node dependencies are installed, the available Node runtime is v22 while the
  project declares Node >=24, and no BeeOne bench is listening on localhost:8000.

Therefore the implementation is verified at source and preference-helper level;
visual layout, breakpoint behavior, persistence after an actual reload, and form
business regression checks still need a live BeeOne Desk run.
