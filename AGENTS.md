# KiraKiraLens Agent Guide

This repository contains a desktop application for designing photographic lenses
from commercially available optical components.

Before planning or changing code, read the complete product and implementation
requirements in [`docs/DEVELOPMENT_PROMPT.md`](docs/DEVELOPMENT_PROMPT.md). Treat
that document as the source of truth unless the user gives newer instructions.
Then read [`docs/IMPLEMENTATION_STATUS.md`](docs/IMPLEMENTATION_STATUS.md) to see
what is already working, what has been verified, and which phase comes next.

## Non-negotiable rules

- Use Optiland as the optical calculation and continuous-optimization engine.
- Build a native desktop application. The preferred UI framework is PySide6.
- Make the interactive lens cross-section the primary editing surface. The
  traditional surface table is a synchronized secondary editor.
- Keep optical-domain data independent from Optiland objects through an adapter.
- Never replace real optical calculations with placeholder results.
- Preserve catalog manufacturer, part number, source, and retrieval date.
- Do not invent missing catalog specifications or glass types.
- A catalog part's prescription is immutable. Editing it creates a custom copy.
- Catalog search must treat part choice/order/orientation as discrete variables
  and air gaps/stop/image position as continuous variables.
- Locks are hard constraints and must never be violated by optimization.
- Work phase by phase, keeping the application runnable and tested after each
  phase.
- Do not read from or modify `C:\Users\tak01\github\kougaku`.

When requirements conflict or optical conventions are ambiguous, record the
assumption in the design documentation and ask the user before making an
irreversible architectural choice.
