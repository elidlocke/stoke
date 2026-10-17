// Fails a deploy (on Render) while any page still shows a TODO: placeholder (src/components/Todo.astro), so a
// half-filled pricing or legal page can't go live. Locally it only warns, so the site still builds while you work.
import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'

const dist = new URL('../dist/', import.meta.url).pathname

function htmlFiles(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
    e.isDirectory() ? htmlFiles(join(dir, e.name)) : e.name.endsWith('.html') ? [join(dir, e.name)] : [],
  )
}

const found = []
for (const file of htmlFiles(dist)) {
  const todos = [...readFileSync(file, 'utf8').matchAll(/TODO: ([^<]*)/g)].map((m) => m[1].trim())
  if (todos.length) found.push(`  ${file.slice(dist.length)}: ${[...new Set(todos)].join('; ')}`)
}

if (found.length) {
  const deploying = Boolean(process.env.RENDER || process.env.CI)
  console[deploying ? 'error' : 'warn'](
    `${deploying ? 'Error' : 'Warning'}: placeholders still to fill in (site/src/business.ts and the pages):\n${found.join('\n')}`,
  )
  if (deploying) process.exit(1)
}
