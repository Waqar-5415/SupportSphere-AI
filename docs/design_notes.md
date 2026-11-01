# Design notes — SupportSphere AI

## Users and goals
| User | Goal | Main path |
|---|---|---|
| Customer | Fast answer to a common problem | AI chat or Help Centre |
| Customer with an unresolved issue | Reach a person and follow progress | Ticket → replies → status |
| Support agent (admin) | Clear the queue, keep answers accurate | Tickets queue, Help articles |

## Flows
```
Landing → Create account → Dashboard → AI Chat → answer → 👍/👎
                                         │  no match → "Open a ticket" (question pre-filled)
                                         └→ Help Centre → search/category → expand answer → still stuck? Ask AI / ticket
Ticket created → agent replies (badge "New reply") → customer replies / closes → agent resolves
Admin: Overview → Tickets (filter) → reply + set status;  Help articles (edit) → instantly used by Chat;  AI engines → test keys
```

## Colour and type
* Primary indigo `#4F46E5` → violet `#7C5CFF` gradient; accent aqua `#0EA5A4`; cool neutral surfaces.
* Semantic colours only for status (blue open, amber in progress, green resolved, grey closed, red high priority).
* System font stack; 16 px base (18.5 px in Large mode); rounded 12–24 px shapes; one elevation scale.
* Full dark theme, followed automatically when the theme is "System".

## HCI principles in the product
| Principle | Where |
|---|---|
| Visibility of system status | Typing indicator, disabled/“Working…” buttons, toasts, status badges with text, "New reply" badge, notice when the AI falls back, engine tag on every answer |
| Match with real world | Plain language, "ticket", "Help Centre", familiar chat layout |
| User control & freedom | Clear / delete conversations, regenerate answer, close/re-open tickets, live preview of theme, cancel on forms |
| Consistency & standards | One shell, one button/badge/card system, same layout for every list/detail |
| Error prevention | Limits + counters, required hints, confirm before destructive actions, password rules shown up-front |
| Recognition over recall | Suggested prompts, category chips, status tabs, always-visible sidebar |
| Flexibility | Keyboard (Enter to send), engine choice, search + browse, mobile layout |
| Minimalist design | 3 primary actions on the dashboard, details progressively disclosed |
| Error recovery | Field-level messages, failed chat message returns to the input, friendly 404/403/500 pages |
| Accessibility | Skip link, landmarks, labels, `aria-live`, `aria-invalid` + linked errors, focus ring, ≥44 px targets, reduced motion, large text, no colour-only meaning |
