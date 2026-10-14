import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useImperativeHandle, useLayoutEffect, useRef, useState, type Ref } from 'react'
import { api, type ActionUpdate, type MergeField, type NoteTemplate } from '../api'
import { Link } from 'react-router'
import { Chip } from '../components/Chip'
import { Filled } from '../components/Filled'
import { formatRelative } from '../format'

// {{name}} or {{name|fallback}}, as app/templates.py reads them.
const FIELD = /(\{\{\s*[a-z_]+\s*(?:\|[^{}]*)?\}\})/

/** Invalidates everything an action's change affects: its page, its queue, and the library. */
export function useInvalidateAction(kind: string) {
  const queryClient = useQueryClient()
  return () =>
    Promise.all(
      [['action', kind], ['action-queue', kind], ['action-history', kind], ['actions'], ['contacted']].map((queryKey) =>
        queryClient.invalidateQueries({ queryKey }),
      ),
    )
}

/** The writer's note for an action: subject and body with {{merge fields}}, edited and approved here. */
export function TemplateEditor({
  kind,
  account,
  template,
  fields,
}: {
  kind: string
  account?: string
  template: NoteTemplate
  fields: MergeField[]
}) {
  const invalidate = useInvalidateAction(kind)
  const [subject, setSubject] = useState(template.subject)
  const [body, setBody] = useState(template.body)
  const subjectRef = useRef<TagEditorHandle>(null)
  const bodyRef = useRef<TagEditorHandle>(null)
  const lastFocus = useRef<'subject' | 'body'>('body')
  const [previewing, setPreviewing] = useState(false)
  // Follow the saved template when it changes (after a save, or another tab's).
  useEffect(() => {
    setSubject(template.subject)
    setBody(template.body)
  }, [template.subject, template.body])

  const save = useMutation({ mutationFn: (update: ActionUpdate) => api.updateAction(kind, update), onSuccess: invalidate })
  const dirty = subject !== template.subject || body !== template.body
  const known = new Set(fields.map((f) => f.name))

  /** Puts the field at the cursor of the box last edited. */
  const insert = ({ name }: MergeField) => (lastFocus.current === 'subject' ? subjectRef : bodyRef).current?.insert(`{{${name}}}`)

  return (
    <section className="template-editor">
      <p className="muted lede-small">
        Write the note once. Each person’s copy fills in the <span className="tag">fields</span> with their own details;
        nothing else changes from person to person.
      </p>
      <div className="field">
        <span id="note-subject">Subject</span>
        <TagEditor
          ref={subjectRef}
          labelId="note-subject"
          value={subject}
          onChange={(v) => setSubject(v.replace(/\n/g, ' '))}
          onFocus={() => (lastFocus.current = 'subject')}
          known={known}
          singleLine
        />
      </div>
      <div className="field">
        <span id="note-body">Note</span>
        <TagEditor
          ref={bodyRef}
          labelId="note-body"
          value={body}
          onChange={setBody}
          onFocus={() => (lastFocus.current = 'body')}
          known={known}
        />
      </div>
      <div className="merge-fields">
        <span className="muted small">Insert:</span>
        {fields.map((f) => (
          <button
            key={f.name}
            type="button"
            className="tag tag-button"
            title={f.description}
            // Keep the cursor where it is in the note while clicking.
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => insert(f)}
          >
            + {label(f.name)}
          </button>
        ))}
      </div>
      {save.isError && <p className="error">{save.error.message}</p>}
      <div className="form-buttons">
        <button type="button" className="ghost" onClick={() => setPreviewing(true)}>
          Preview
        </button>
        {dirty ? (
          <>
            <button className="primary" disabled={save.isPending} onClick={() => save.mutate({ subject, body, approved: true })}>
              Save and approve
            </button>
            <button className="ghost" disabled={save.isPending} onClick={() => save.mutate({ subject, body })}>
              Save draft
            </button>
            <button
              className="link"
              onClick={() => {
                setSubject(template.subject)
                setBody(template.body)
              }}
            >
              Discard changes
            </button>
          </>
        ) : template.approved_at ? (
          <>
            <Chip tone="ok">Approved {formatRelative(template.approved_at)}</Chip>
            <button className="link" disabled={save.isPending} onClick={() => save.mutate({ approved: false })}>
              Withdraw approval
            </button>
          </>
        ) : (
          <>
            <button className="primary" disabled={save.isPending} onClick={() => save.mutate({ approved: true })}>
              Approve
            </button>
            <span className="muted small">
              {template.is_default ? 'Stoke’s starting point: edit it to sound like you.' : 'Saved, not approved yet.'}
            </span>
          </>
        )}
      </div>
      {previewing && (
        <NotePreview kind={kind} account={account} subject={subject} body={body} onClose={() => setPreviewing(false)} />
      )}
    </section>
  )
}

/**
 * The draft as it'll read, filled in for a few real people in the audience (one without a first name, if there is
 * one, so the fallback shows); for an example reader when nobody's in it.
 */
function NotePreview({
  kind,
  account,
  subject,
  body,
  onClose,
}: {
  kind: string
  account?: string
  subject: string
  body: string
  onClose: () => void
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  const [at, setAt] = useState(0)
  const preview = useQuery({
    queryKey: ['note-preview', kind, account, subject, body],
    queryFn: () => api.previewNote(kind, { subject, body }, account),
  })
  useEffect(() => {
    // Effects run twice in development; opening an open dialog again throws in some browsers.
    if (dialog.current && !dialog.current.open) dialog.current.showModal()
  }, [])
  const readers = preview.data?.readers ?? []
  const reader = readers[Math.min(at, readers.length - 1)]

  return (
    <dialog
      ref={dialog}
      className="preview-dialog"
      aria-labelledby="preview-title"
      onClose={onClose}
      // A click on the backdrop lands on the dialog itself; the content is inside .preview-content.
      onClick={(e) => e.target === dialog.current && dialog.current.close()}
    >
      <div className="preview-content">
        <header className="preview-header">
          <h2 id="preview-title">Preview</h2>
          {readers.length > 1 && (
            <div className="preview-nav">
              <button type="button" className="ghost" aria-label="Previous reader" disabled={at === 0} onClick={() => setAt(at - 1)}>
                ‹
              </button>
              <span className="muted small">
                {at + 1} of {readers.length}
              </span>
              <button
                type="button"
                className="ghost"
                aria-label="Next reader"
                disabled={at === readers.length - 1}
                onClick={() => setAt(at + 1)}
              >
                ›
              </button>
            </div>
          )}
        </header>
        {preview.isPending && <p className="muted">Filling in the note…</p>}
        {preview.isError && <p className="error">{preview.error.message}</p>}
        {preview.data && reader && (
          <>
            <p className="muted small">
              {preview.data.example ? (
                'Nobody is in this audience right now, so this is an example reader with made-up details.'
              ) : (
                <>
                  As sent to <strong>{reader.email}</strong> · {reader.why}
                </>
              )}
            </p>
            <div className="note">
              <div className="note-subject">
                <Filled parts={reader.note.subject} />
              </div>
              <div className="note-body">
                <Filled parts={reader.note.body} />
              </div>
            </div>
            {reader.note.missing.length > 0 && (
              <p className="warning small">
                Nothing to fill in for {reader.note.missing.map(label).join(', ')}. Add it in{' '}
                <Link to="/settings">Settings</Link>.
              </p>
            )}
          </>
        )}
        <div className="form-buttons">
          <button type="button" className="primary" onClick={() => dialog.current?.close()}>
            Close
          </button>
        </div>
      </div>
    </dialog>
  )
}

interface TagEditorHandle {
  insert: (token: string) => void
}

const label = (name: string) => name.replace(/_/g, ' ')

/** The field name in {{name}} (or an older template's {{name|fallback}}). */
const tokenName = (token: string) => token.match(/^\{\{\s*([a-z_]+)/)?.[1] ?? ''

/**
 * A text box that shows merge fields as tags rather than {{braces}}. The value is still the plain template text; each
 * tag is an uneditable element carrying its {{token}}, so it can be deleted whole but never half-edited.
 */
function TagEditor({
  ref,
  labelId,
  value,
  onChange,
  onFocus,
  known,
  singleLine = false,
}: {
  ref: Ref<TagEditorHandle>
  labelId: string
  value: string
  onChange: (v: string) => void
  onFocus: () => void
  known: Set<string>
  singleLine?: boolean
}) {
  const root = useRef<HTMLDivElement>(null)
  const saved = useRef<Range | null>(null)

  // Redraw from the value only when it differs from what's on screen (a load, a discard), not on every keystroke.
  useLayoutEffect(() => {
    if (root.current && serialize(root.current, true) !== value) render(root.current, value, known)
  })

  // Remember where the cursor was, so Insert can put a field there after focus has moved to the button.
  useEffect(() => {
    const remember = () => {
      const sel = document.getSelection()
      if (sel?.rangeCount && root.current?.contains(sel.anchorNode)) saved.current = sel.getRangeAt(0).cloneRange()
    }
    document.addEventListener('selectionchange', remember)
    return () => document.removeEventListener('selectionchange', remember)
  }, [])

  const emit = () => root.current && onChange(serialize(root.current, true))

  useImperativeHandle(ref, () => ({
    insert(token) {
      const el = root.current
      if (!el) return
      el.focus()
      const range = saved.current && el.contains(saved.current.startContainer) ? saved.current : endOf(el)
      range.deleteContents()
      const tag = makeTag(token, known)
      range.insertNode(tag)
      range.setStartAfter(tag)
      range.collapse(true)
      select(range)
      emit()
    },
  }))

  /** Typing {{name}} by hand, or pasting it, turns it into a tag; stray markup from the browser is flattened. */
  const onInput = () => {
    const el = root.current
    if (!el) return
    const text = serialize(el, true)
    const untidy = [...el.childNodes].some(
      (n) => (n instanceof Text && FIELD.test(n.data)) || (n instanceof HTMLElement && !n.dataset.token && n.tagName !== 'BR'),
    )
    if (untidy) {
      const caret = caretOffset(el)
      render(el, text, known)
      if (caret !== null) placeCaret(el, caret)
    }
    onChange(text)
  }

  return (
    <div className={`tag-editor${singleLine ? ' single' : ''}`}>
      <div
        ref={root}
        className="tag-input"
        contentEditable
        suppressContentEditableWarning
        role="textbox"
        aria-multiline={!singleLine}
        aria-labelledby={labelId}
        spellCheck
        onFocus={onFocus}
        onInput={onInput}
        onKeyDown={(e) => {
          if (e.key !== 'Enter') return
          e.preventDefault()
          if (!singleLine) lineBreak()
          emit()
        }}
        onPaste={(e) => {
          e.preventDefault()
          const text = e.clipboardData.getData('text/plain')
          document.execCommand('insertText', false, singleLine ? text.replace(/\s*\n\s*/g, ' ') : text)
        }}
      />
    </div>
  )
}

function makeTag(token: string, known: Set<string>): HTMLElement {
  const name = tokenName(token)
  const tag = document.createElement('span')
  tag.className = known.has(name) ? 'tag' : 'tag unknown'
  tag.contentEditable = 'false'
  tag.dataset.token = token
  tag.title = known.has(name) ? 'Filled in for each person' : `Stoke doesn’t know a “${label(name)}” field, so this won’t fill in.`
  tag.textContent = label(name)
  return tag
}

/** Draws the template text: plain text, line breaks, and a tag per merge field. */
function render(el: HTMLElement, text: string, known: Set<string>) {
  el.replaceChildren()
  text.split(FIELD).forEach((piece, i) => {
    if (i % 2) return el.append(makeTag(piece, known))
    piece.split('\n').forEach((line, j) => {
      if (j) el.append(document.createElement('br'))
      if (line) el.append(line)
    })
  })
  // A trailing line break only shows with another after it; serialize() skips that placeholder.
  if (text.endsWith('\n')) el.append(document.createElement('br'))
}

/** The template text behind what's on screen: tags back to {{tokens}}, line breaks to \n. */
function serialize(node: Node, whole = false): string {
  let out = ''
  const kids = [...node.childNodes]
  if (whole && kids.at(-1)?.nodeName === 'BR') kids.pop()
  for (const n of kids) {
    if (n instanceof Text) out += n.data.replace(/[ ]/g, ' ').replace(/​/g, '')
    else if (n instanceof HTMLElement && n.dataset.token) out += n.dataset.token
    else if (n.nodeName === 'BR') out += '\n'
    else {
      // Blocks the browser may wrap lines in (a <div> per line) start on a new line.
      if (/^(DIV|P)$/.test(n.nodeName) && out && !out.endsWith('\n')) out += '\n'
      out += serialize(n)
    }
  }
  return out
}

/** The cursor's position in the template text, or null if it isn't in the box. */
function caretOffset(el: HTMLElement): number | null {
  const sel = document.getSelection()
  if (!sel?.rangeCount || !el.contains(sel.focusNode)) return null
  const before = document.createRange()
  before.setStart(el, 0)
  before.setEnd(sel.focusNode!, sel.focusOffset)
  return serialize(before.cloneContents()).length
}

/** Puts the cursor at a position in the template text (after a redraw). */
function placeCaret(el: HTMLElement, offset: number) {
  const range = document.createRange()
  let left = offset
  for (const n of el.childNodes) {
    const len = n instanceof Text ? n.data.length : n instanceof HTMLElement && n.dataset.token ? n.dataset.token.length : 1
    if (left <= len && n instanceof Text) {
      range.setStart(n, left)
      return select(range)
    }
    if (left < len) {
      range.setStartBefore(n)
      return select(range)
    }
    left -= len
  }
  select(endOf(el))
}

/** A line break at the cursor; by hand where the browser has no insertLineBreak command (Firefox). */
function lineBreak() {
  if (document.execCommand('insertLineBreak')) return
  const range = document.getSelection()?.getRangeAt(0)
  if (!range) return
  range.deleteContents()
  const br = document.createElement('br')
  range.insertNode(br)
  // At the very end, a break needs another after it to show.
  if (!br.nextSibling) br.after(document.createElement('br'))
  range.setStartAfter(br)
  select(range)
}

function endOf(el: HTMLElement): Range {
  const range = document.createRange()
  range.selectNodeContents(el)
  range.collapse(false)
  return range
}

function select(range: Range) {
  range.collapse(true)
  const sel = document.getSelection()
  sel?.removeAllRanges()
  sel?.addRange(range)
}
