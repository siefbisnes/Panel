# Adding an application

Create `database/applications/<id>.yaml`. The file name must match `id`. An application definition is
reviewable metadata: it describes how to detect an app, which package names install it, where its
configuration lives, and which facts/controls are safe to present in Linux System. It is not an
installer script.

```yaml
schema_version: 1
id: rofi                      # lowercase letters, digits, dashes
name: Rofi
category: launcher            # desktop, bar, terminal, shell, launcher, editor, browser, tool, audio, ...
detection:                    # at least one rule
  executables: [rofi]         # names looked up in $PATH
  config_paths:               # ~, $HOME and $XDG_{CONFIG,DATA,STATE,CACHE}_HOME are expanded
    - ~/.config/rofi
  desktop_entries: [rofi]     # .desktop file names without the extension
  processes: [rofi]           # defaults to executables when omitted
  services:                   # systemd units
    user: [rofi.service]
  weights: { executable: 4 }  # optional per-signal confidence weights
packages:                     # exact package identifiers, grouped by package source
  fedora: [rofi]
  arch: [rofi]
  debian: [rofi]
  opensuse: [rofi]
compatibility:                # optional; add only verified claims
  desktop_environments:
    hyprland: supported       # supported, partial, or unsupported
  display_servers:
    wayland: supported
configuration:
  files:                      # a plain path or {path, format}
    - path: ~/.config/rofi/config.rasi
      format: rasi
documentation:                # official sources first; keys are lowercase words
  configuration: https://davatorium.github.io/rofi/
```

To expose safe GUI controls, declare scalar settings on a config-file object:

```yaml
configuration:
  files:
    - path: ~/.config/demo/init.lua
      format: lua
      settings:
        - key: Brightness
          label: Brightness
          type: integer
          minimum: 0
          maximum: 100
          default: 70
          description: Screen brightness percentage.
```

Supported control types are `boolean`, `integer`, `number`, `string`, and `choice` (with a `choices`
list). Numeric settings can declare `minimum`, `maximum`, and `step` when the application defines
useful limits. The editor reads only declared keys and never executes Lua. Adapters are available for
Lua scalar assignments, INI, space-delimited values, Fish `set` values, Vim `set` options, plain JSON,
and block properties in Hyprlang, Rasi, and CSS.
Line-based and block adapters preserve unrelated lines and comments. Saves write only settings changed
from their current values/defaults. Plain JSON supports nested keys using dot notation; JSONC remains
text-only so comments are not lost. Repeatable directives, shortcuts, executable hooks, and other
structured values that do not fit a single scalar control should remain text-editable. `syntax` may be
set to `lua`, `equals`, `space`, `ini`, `json`, `fish`, `vim`, or `block` when format inference is
ambiguous. Other formats remain available through **Open as text** and are not rewritten by the GUI
form.

## Field Guidance

- **ID and file name:** use a stable lowercase ID with digits or hyphens, and save it as
  `<id>.yaml`. Do not rename published IDs casually; local/community definitions override by ID.
- **Category:** choose the closest supported category from the schema. Avoid inventing a new category
  for one application.
- **Detection:** include at least one useful rule. Prefer stable executable names; add desktop entries,
  processes, services, and config paths only when they improve detection. Config paths alone mean
  configuration-only, not installed.
- **Packages:** use exact package names for the supported keys: `fedora`, `arch`, `debian`, `opensuse`,
  and `flatpak`. A name is the identifier used by that package manager, not necessarily the app's
  display name or executable. For Flatpak, use the app ID available from Flathub. Never put shell
  commands, URLs, version constraints, or install flags here.
- **Compatibility:** only claim `supported`, `partial`, or `unsupported` when verified. Keys identify
  desktop environments or display servers, such as `hyprland`, `sway`, `wayland`, or `x11`. Omitted
  support is shown as “Not specified”, not inferred.
- **Configuration:** use `configuration.files` for files that can be opened or described. Supply the
  real format. Add `settings` only for individual scalar options you have verified against the app's
  own documentation. Numeric controls should have useful bounds and step values; choices must list
  valid values. The editor changes only declared settings and saves changed values, leaving unrelated
  text intact for supported adapters.
- **Documentation:** use official project documentation first, with stable HTTPS URLs and descriptive
  keys such as `official`, `configuration`, or `home`.

Only list paths the application itself reads. Do not label cache/data paths as configuration. List
configuration files in the order the user is likely to edit them. Complex config formats, repeatable
directives, bindings, and scripts should remain available through the text editor instead of being
represented as misleading scalar controls.

## Package Mapping In More Detail

Package mappings tell Linux System which exact identifiers to check in the local package index and
which name to offer to the Store. The schema accepts only these keys: `fedora`, `arch`, `debian`,
`opensuse`, and `flatpak`. Mappings are optional; leave a key out when you cannot verify it rather
than filling in a guess.

Use block YAML lists. They are more verbose than inline lists, but alternatives and review changes
are easier to see:

```yaml
packages:
  fedora:
    - example-package
  arch:
    - example-package
  debian:
    - example-package
    - example-package-alt
  opensuse:
    - example-package
  flatpak:
    - org.example.App
```

### Find And Verify A Package

1. **Identify the actual package source.** Search the target distro's official package index or query
   a machine running that distro. Record the package name exactly as published, including spelling,
   punctuation, and case. Do not derive it from the app's display name or executable.

2. **Confirm it is the right application.** Check the package description, upstream project, and
   provided executable or application ID. Avoid similarly named forks, libraries, development
   packages, plugins, language bindings, and metapackages unless that package is genuinely the app
   users expect.

3. **Check availability in the intended repository.** These commands inspect package metadata; they
   are examples for a matching distro and are not YAML values:
   
   | Mapping            | Example lookup                         |
   | ------------------ | -------------------------------------- |
   | Fedora             | `dnf info <package>`                   |
   | Arch               | `pacman -Si <package>`                 |
   | Debian/Ubuntu      | `apt show <package>`                   |
   | openSUSE           | `zypper info <package>`                |
   | Flatpak on Flathub | `flatpak remote-info flathub <app-id>` |

4. **Use the right identifier type.** For native packages, use the repository's package name. For
   Flatpak, use the exact Flathub application ID, not the display title or native package name. Store
   Flatpak installs currently use the `flathub` remote.

5. **Only claim what you checked.** If you could not verify openSUSE, omit `opensuse`. A missing
   mapping means coverage is unknown; it does not mean the application is unavailable there.

Local queries can be misleading when repositories are disabled or package metadata is stale. When
you cannot query a matching system, use the distro's official package search and mention that source
in your pull request. Linux System currently recognizes native packages through RPM (Fedora and
openSUSE), pacman (Arch), and dpkg (Debian), plus Flatpak. Other distributions are not automatically
covered just because they use one of these package formats.

### Order Alternatives Deliberately

Each package list must be non-empty, contain unique strings, and use identifiers accepted by the
schema. Multiple names are useful for genuine variants, not as a list of guesses.

- Put the preferred native install candidate first. For a new install, the Store selects the first
  mapped native name for the detected distro.
- Later native names can help Linux System recognize an alternative that is already installed. They
  are **not** install retries: if the first package is unavailable or fails to install, the Store
  does not try the next list item.
- The Store selects a Flatpak mapping when the current distro has no usable native mapping/backend
  and Flatpak is available. It does not automatically fall back to Flatpak after a native install
  attempt fails.
- Flatpak lists follow the same ordering rule: the first ID is the Store install candidate; later IDs
  may be checked for an already installed match.
- Do not list packages that install different apps under one definition just to broaden detection.

For example, this Debian mapping recognizes both packages but tries `example-package` first for a new
install:

```yaml
packages:
  debian:
    - example-package
    - example-package-esr
```

Only reverse that order when the second variant is the better default for Debian users. Because an
install invokes the system package manager, verify the first choice especially carefully.

### Example: Firefox

The bundled Firefox definition maps the native packages and Flatpak ID separately:

```yaml
packages:
  fedora: [firefox]
  arch: [firefox]
  debian: [firefox, firefox-esr]
  flatpak: [org.mozilla.firefox]
```

The Debian list helps recognize either installed variant. Because `firefox` comes first, it is the
current install candidate there. Do not copy this mapping blindly for another app; use it as an
example of the YAML shape and verify every name for the target distro.

### Package Definition Checklist

Before submitting a mapping, check that:

- The distro key is one of `fedora`, `arch`, `debian`, `opensuse`, or `flatpak`.
- Each value is a valid package identifier and the package is available from the intended repository.
- The package provides this app, rather than a related component or a differently branded fork.
- The first native name is the one you'd want Linux System to try for a fresh install.
- Each alternative is a real variant you want detection to recognize; no duplicate or speculative
  names are included.
- Flatpak values are exact Flathub application IDs.
- Package names are checked against current package metadata or an official package listing, and the
  PR description says what source or system you used to check them.

### Safely Test A Mapping

Schema validation does not contact repositories, prove a package exists, or test whether installation
works. Check names with the package metadata lookups above. For an end-to-end Store install test, use
a disposable VM or test machine on the target distro/release, review the package-manager prompt, and
record the result. Do not experiment with installs or removals on a system where an unexpected change
would be costly. If you only performed metadata and schema checks, say so in the PR; don't imply that
the package was installed successfully.

## A Good Contribution Workflow

Keep each definition focused on one application and make the evidence easy for someone else to
review. A small, verified definition is more useful than a large definition full of assumptions.

1. **Check for an existing definition first.** Search `database/applications/` for the app and
   related IDs. Extend or correct the existing definition rather than adding a duplicate under a new
   name.
2. **Use a stable ID and filename.** Choose a lowercase ID with digits or hyphens, then use the same
   value for `id` and `<id>.yaml`. IDs are how database layers override one another; changing a
   published ID can leave duplicate entries behind.
3. **Use readable YAML.** Use two spaces per YAML nesting level, never tabs. Keep top-level keys in
   the example order (`schema_version`, identity fields, `detection`, `packages`, then optional
   metadata). Use block lists for multiple package names or detection signals. Quote strings when
   YAML punctuation could change their meaning. Keep `packages` at the top level, as a sibling of
   `detection`, not inside it.
4. **Add only verified facts.** Confirm each package mapping and detection signal independently.
   Link official documentation where possible. Leave compatibility or distro coverage unspecified
   when you have not tested or confirmed it.
5. **Keep configuration controls conservative.** Add only real config paths and scalar settings
   documented by the upstream app. Do not expose scripts, hooks, arbitrary commands, or complex
   repeatable structures as simple GUI controls.
6. **Validate and inspect the definition locally.** Run the checks below and fix every schema or
   loading issue before opening a PR. Validation cannot verify remote package availability.
7. **Write a review-friendly PR description.** Say what the definition adds, list the package sources
   or distro/release versions you checked, mention any install test and where it ran, and clearly note
   anything you could not verify. Include links to package indexes or upstream docs rather than only
   saying "works on my machine".

Avoid bundling unrelated code cleanup or changing other applications' definitions in the same PR.
That keeps review focused and makes it easier to correct a package mapping if repository details
change later.

## Test Locally

Validate one definition and inspect how Linux System loads it. Replace `<id>` with the filename stem:

```bash
.venv/bin/linux-system validate database/applications/<id>.yaml
.venv/bin/linux-system --db database info <id>
.venv/bin/linux-system --db database config <id>
```

The validator checks YAML syntax, schema fields, and the `id`/filename match. The `info` and `config`
commands check that the definition loads and show how its metadata is interpreted. None of these
commands installs a package or confirms that a package exists in a remote repository; use the package
metadata lookups above for that. For actual Store install behavior, use a disposable VM or test system
as described in [Safely Test A Mapping](#safely-test-a-mapping).

For a local override, put the definition at
`$XDG_CONFIG_HOME/linux-system/database/applications/<id>.yaml` and run the normal scan. Or test an
unmerged directory with `--db DIR`.

## Submit A Suggestion

The CLI can create a reviewable starting point:

```bash
linux-system submit \
  --id example-app \
  --name "Example App" \
  --category tool \
  --executable example-app \
  --config '~/.config/example-app/config' \
  --package example-app \
  --distro fedora \
  --docs https://example.org/docs
```

This writes a schema-validated YAML file under
`$XDG_DATA_HOME/linux-system/submissions/`. It does **not** install the app, publish the file, or add
it to the trusted database. A maintainer must review it and merge it into the bundled or community
database before other users receive it.

The `submit` command currently supports one executable, repeated config paths, one package mapping,
and one docs link. For compatibility metadata, multiple distro package names, configuration options,
services, or other richer definitions, author the YAML file directly using the example above and open
a pull request.

## Share A Reviewed Definition

For a shared bundled definition, submit `database/applications/<id>.yaml` in a pull request. For a
separately maintained community database, add the file there and submit its repository through the
project's contribution/review process. Users can then load that repository with:

```bash
linux-system update-db --source <git-url>
```

Subsequent `update-db` runs fast-forward the configured community database. The app loads bundled
definitions first and later trusted layers override an earlier entry with the same ID.

Before opening a pull request, validate the full bundle and run the test suite:

```bash
.venv/bin/linux-system validate
.venv/bin/python -m pytest -q
```

Definitions never execute code during scanning. Do not add scripts, install hooks, or shell fragments
to application metadata.
