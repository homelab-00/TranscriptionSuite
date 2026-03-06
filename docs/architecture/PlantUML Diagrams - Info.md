# Architecture Diagrams

PlantUML diagrams documenting the TranscriptionSuite codebase architecture.

## Diagrams

| File | Description |
|------|-------------|
| `overview.puml` | High-level system architecture (Electron, FastAPI, data layer, external services) |
| `server-api.puml` | Server API routing, middleware stack, and lifespan lifecycle |
| `stt-backends.puml` | STT backend class hierarchy, factory pattern, and model manager |
| `dashboard-components.puml` | React component tree, hooks, services, and their relationships |
| `data-flow.puml` | Sequence diagrams for longform, file upload, and live mode transcription |

## How to Render

### VS Code (recommended)
1. Install the [PlantUML extension](https://marketplace.visualstudio.com/items?itemName=jebbs.plantuml) (`jebbs.plantuml`)
2. Open any `.puml` file
3. Press `Alt+D` to preview

Requires either a local PlantUML server or Java + Graphviz. The extension settings let you choose a render method.

### Command Line
```bash
# Requires Java and plantuml.jar
java -jar plantuml.jar overview.puml           # renders to overview.png
java -jar plantuml.jar -tsvg overview.puml     # renders to overview.svg
java -jar plantuml.jar "*.puml"                # render all diagrams
```

### Online
Paste the contents of any `.puml` file at [plantuml.com/plantuml](https://www.plantuml.com/plantuml/uml/).
