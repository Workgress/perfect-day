import { spawn } from 'node:child_process'
import { mkdtemp, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import path from 'node:path'
const output = await mkdtemp(path.join(tmpdir(), 'perfect-day-today-states-'))
const chrome = spawn('C:/Program Files/Google/Chrome/Application/chrome.exe', ['--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check', '--remote-debugging-port=0', `--user-data-dir=${path.join(output, 'profile')}`, 'about:blank'], { windowsHide: true, stdio: ['ignore', 'ignore', 'pipe'] })
let socket
try {
  const endpoint = await new Promise((resolve, reject) => {
    let buffer = ''
    const timer = setTimeout(() => reject(new Error('Chrome startup timed out')), 15000)
    chrome.stderr.on('data', chunk => { buffer += chunk; const match = buffer.match(/DevTools listening on (ws:\/\/[^\s]+)/); if (match) { clearTimeout(timer); resolve(match[1]) } })
  })
  const port = new URL(endpoint).port
  const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()
  socket = new WebSocket(targets.find(t => t.type === 'page').webSocketDebuggerUrl)
  await new Promise(resolve => socket.addEventListener('open', resolve, { once: true }))
  let sequence = 0
  const pending = new Map(), errors = []
  socket.addEventListener('message', event => {
    const msg = JSON.parse(event.data)
    if (msg.id) { const callbacks = pending.get(msg.id); if (callbacks) { pending.delete(msg.id); msg.error ? callbacks.reject(msg.error) : callbacks.resolve(msg.result) } }
    if (msg.method === 'Runtime.exceptionThrown') errors.push(msg.params.exceptionDetails.text + ' ' + (msg.params.exceptionDetails.exception?.description ?? ''))
  })
  const send = (method, params = {}) => new Promise((resolve, reject) => { const id = ++sequence; pending.set(id, { resolve, reject }); socket.send(JSON.stringify({ id, method, params })) })
  const evaluate = async expression => { const result = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true }); if (result.exceptionDetails) throw new Error(result.exceptionDetails.text); return result.result.value }
  const waitFor = async expression => { for (let i = 0; i < 80; i++) { if (await evaluate(expression)) return; await new Promise(resolve => setTimeout(resolve, 100)) } throw new Error(`Timed out: ${expression}`) }
  const click = text => evaluate(`(() => { const root=[...document.querySelectorAll('dialog[open]')].at(-1) ?? document; const button = [...root.querySelectorAll('button')].find(b => b.textContent.trim() === ${JSON.stringify(text)}); if (!button) throw new Error('Missing button'); button.click(); })()`)
  await send('Page.enable'); await send('Runtime.enable')
  const results = []
  for (const viewport of [{ width: 1440, height: 1000, theme: 'dark' }, { width: 430, height: 932, theme: 'light' }, { width: 360, height: 800, theme: 'dark' }, { width: 320, height: 568, theme: 'dark' }, { width: 390, height: 844, theme: 'light' }]) {
    await send('Emulation.setDeviceMetricsOverride', { width: viewport.width, height: viewport.height, deviceScaleFactor: 1, mobile: false })
    for (const mode of ['loading', 'end', 'delete', 'move', 'deadline', 'review', 'replan']) {
      await send('Page.navigate', { url: `http://127.0.0.1:5177/today-state-preview.html?case=${mode}&theme=${viewport.theme}` })
      await waitFor("!!document.querySelector('h1')")
      await evaluate('document.fonts.ready')
      if (mode === 'loading') await waitFor("!!document.querySelector('[aria-label=\"Загружаем план дня\"]')")
      if (mode === 'end') await waitFor("!!document.querySelector('[aria-label=\"Итог дня\"]') && document.body.textContent.includes('Задач в плане:')")
      if (mode === 'delete') { await waitFor("!!document.querySelector('dialog button') && document.body.textContent.includes('Удалить задачу')"); await click('Удалить задачу') }
      if (mode === 'move') {
        await waitFor("[...document.querySelectorAll('button')].some(b => b.textContent.trim() === 'Перенести' && !b.disabled)")
        await click('Перенести')
        await evaluate(`(() => { const field = document.querySelector('input[type="datetime-local"]'); Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(field, '2026-11-12T11:00'); field.dispatchEvent(new Event('input', { bubbles: true })); field.dispatchEvent(new Event('change', { bubbles: true })); })()`)
        await click('Сохранить время')
      }
      if (mode === 'deadline') await waitFor("document.body.textContent.includes('Нет свободного окна')")
      if (mode === 'review') await waitFor("document.body.textContent.includes('Результат перепланирования')")
      if (mode === 'replan') { await waitFor("[...document.querySelectorAll('button')].some(b => b.textContent.trim() === 'Перепланировать' && !b.disabled)"); await click('Перепланировать') }
      if (mode === 'deadline') await evaluate(`document.querySelector('[aria-label="Проверка срока"]').scrollIntoView({block:'center'})`)
      await new Promise(resolve => setTimeout(resolve, 150))
      const metrics = await evaluate(`(() => { const d=[...document.querySelectorAll('dialog[open]')].at(-1); const r=d?.getBoundingClientRect(); return { overflow: document.documentElement.scrollWidth > innerWidth, dialog: r ? { x:r.x,y:r.y,width:r.width,height:r.height, scrollHeight:d.scrollHeight,clientHeight:d.clientHeight } : null, focus: document.activeElement?.textContent?.trim().slice(0,80) } })()`)
      const label = `${mode}-${viewport.width}-${viewport.theme}`
      const shot = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false })
      await writeFile(path.join(output, label + '.png'), Buffer.from(shot.data, 'base64'))
      results.push({ label, ...metrics })
      if (mode === 'move' || mode === 'delete') {
        await click(mode === 'move' ? 'Перенести' : 'Удалить')
        await waitFor(`!document.querySelector('dialog[open]') && document.body.textContent.includes('${mode === 'move' ? 'Задача перенесена' : 'Задача удалена'}')`)
        const toast = await send('Page.captureScreenshot', { format:'png', captureBeyondViewport:false })
        await writeFile(path.join(output, `${mode}-success-${viewport.width}-${viewport.theme}.png`), Buffer.from(toast.data,'base64'))
        results.push({ label: `${mode}-success-${viewport.width}-${viewport.theme}`, overflow: await evaluate('document.documentElement.scrollWidth > innerWidth') })
      }
    }
  }
  await writeFile(path.join(output, 'results.json'), JSON.stringify({ results, errors }, null, 2))
  console.log(JSON.stringify({ output, results, errors }))
} finally { socket?.close(); chrome.kill() }
