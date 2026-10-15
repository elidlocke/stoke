# UI style guide

How Stoke's screens are put together, so a new section looks and behaves like the ones already there. Settings is the reference: [frontend/src/pages/Settings.tsx](../frontend/src/pages/Settings.tsx) and the `Settings*.tsx` pages beside it.

## Buttons and links

Each kind of button does one job. Pick by what the click does, not by how prominent you'd like it to look.

| Kind | Looks like | Use it for | Example |
|---|---|---|---|
| **Call to action** | `<Cta>` ([Cta.tsx](../frontend/src/components/Cta.tsx)): orange, one size everywhere | The one thing to do in an **empty** section | Connect with Stripe, Add a revenue stream, Connect Gmail |
| **Secondary** | `button.ghost` (`.add-link` under a list) | Adding one more of something to a section that already has some | Add a channel, Connect another Stripe account |
| **Link button** | `button.link` | An action on a single item, in its row | Edit, Rename, Re-check, Confirm |
| **Destructive** | `button.link.danger` in a row; `button.danger` to confirm | Removing or disconnecting. Always behind an inline confirm, never on the first click | Remove, Disconnect |
| **Form buttons** | `button.primary` to submit, then `button.ghost` to cancel | Submitting a form that's open | Save, Add, Cancel |

Rules for calls to action:
- At most one per section.
- Show it while the section is empty. Once the section has content, hide it, or swap it for a secondary button when adding more is still useful.
- Exception: an action the writer should keep coming back to stays a call to action even when the section is filled. **Upload export / Upload newer** on each publication is the one today.
- Inside a list row, use `<Cta small>` so it sits beside the row's link buttons. Make it `outline` when the item is fine as it is (a current export) and solid when there's something to fix (not uploaded, out of date).
- A link that does a CTA's job (e.g. "Add your Substack" pointing at another section) uses `a.button.primary.cta`, so it matches.
- Put it after the section's content. When it stands alone, wrap it in `.section-cta`, which gives it the same spacing as `.add-link`.

## Section anatomy

```
<section className="settings-section full">
  <h2 id="anchor">Section name</h2>          ← sentence case, no number, no chip
  <p className="muted lede-small">…</p>      ← one line: what it is and what it unlocks
  {errors}                                   ← p.error, next to what failed
  <ListBox …>…</ListBox>                     ← the content
  {call to action or secondary button}
</section>
```

- Every section has an `id`, so Home and other pages can link straight to it (`/settings#plans`). Don't rename an id without updating its links.
- Status belongs on the items, not the heading.
- Sections sit in groups (`h2.settings-group`) in the order a writer works through them: connect, refine, start engaging.

## Lists

Anything the writer has connected or confirmed is a `ListBox` of `ListItem`s ([ListBox.tsx](../frontend/src/components/ListBox.tsx)). Don't build a `<table>` in Settings.

```tsx
<ListBox head="Name" columns={[{ label: 'Link', wide: true }, 'Payment']}>
  <ListItem
    title={…} meta={…}                       // name, plus a muted line under it
    fields={[{ label: 'Link', value: … }, { label: 'Payment', value: … }]}  // in columns' order
    status={<ItemStatus … />}
    actions={<>link buttons</>}
    expanded={editing && <form …>}           // edit or remove form, full width under the item
  />
</ListBox>
```

- `head` titles the first column. Leave it out only when a box mixes different kinds of items (the Substack profile and its publications).
- Mark a column `wide` when it holds long text such as a URL.
- Text wraps inside its column. A box never scrolls sideways.
- On phones the header row hides, each item stacks, and every field shows its own label.

## Status

Every item's status is an `ItemStatus`: a chip, an optional fix next to it, and a line of detail.

```tsx
<ItemStatus tone="warn" label="Missing Invoices: Read" action={<button className="link">Re-check</button>} detail="Checked 2 hours ago" />
```

| Tone | Means | Example |
|---|---|---|
| `ok` | Working or confirmed | Connected, Confirmed, Uploaded, Tracking sales |
| `warn` | Works, but needs attention soon | Out of date, Missing permissions, No sales matched yet |
| `bad` | Broken until the writer fixes it | Disconnected in Stripe, Needs reconnecting |
| `neutral` | Not done yet, or Stoke's guess | Not uploaded, Stoke’s guess, Can’t see sales |
| `accent` | An attribute rather than a state (use `Chip` directly, beside the title) | Live |

- The chip's label is a short state of two or three words. The fix goes in `action`, and the explanation goes in `detail`.
- A guess the writer can confirm uses `Confirmation` ([Confirmation.tsx](../frontend/src/components/Confirmation.tsx)): Stoke’s guess + Confirm, or Confirmed + Use Stoke’s guess.

## Type sizes

Three sizes, each with one job. Don't reach for `.small` to make something feel less important; use `.muted` for that.

| Size | Used for |
|---|---|
| **15px** (body) | Titles, field values, and **everything clickable** in a row: link buttons (Edit, Confirm, Re-check, Unlink), whether they sit in the actions column or beside a status chip |
| **13px** (`.small`) | Non-clickable secondary text: an item's `meta` line, a status `detail` line, footnotes, and the `<Cta small>` button |
| **12px** | Chips and column headers |

A link never goes inside a 13px line. If a detail needs a fix (e.g. "Import failed."), put the fix in the row's actions ("Retry import").

## Copy

- US spelling. Dates are month first, via `formatDate` and `formatRelative` ([format.ts](../frontend/src/format.ts)).
- Curly apostrophes and quotes in UI text: ’ “ ”.
- Sentence case for headings, buttons and chips.
- Name the reward. A step says what it unlocks ("Unlocks Free → paid"), and an error says what to do next.
- Address the writer as "you". Their readers are "readers" or "subscribers", never "users".

## Setup checklist

Home's "Finish setting up" ([Home.tsx](../frontend/src/pages/Home.tsx), `SetupChecklist`) lists the Settings sections in the same order, each linking to its section's `id`. A new Settings step gets a checklist item. Data that can't be loaded counts as done, so a broken query never nags.
