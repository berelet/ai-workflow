#!/usr/bin/env node
// Парсит HTML через Puppeteer (computed styles) и создаёт макет в Figma через MCP
// Usage: node html-to-figma.js design.html <figma-channel> [frame-name]

const puppeteer = require('puppeteer-core');
const path = require('path');
const { spawn } = require('child_process');
const readline = require('readline');

const BUN = process.env.BUN_PATH || '/home/aimchn/.bun/bin/bun';
const MCP_SERVER = path.join(__dirname, '..', 'figma-mcp', 'src', 'talk_to_figma_mcp', 'server.ts');

async function extractElements(htmlPath) {
  const browser = await puppeteer.launch({
    executablePath: '/usr/bin/google-chrome',
    args: ['--no-sandbox', '--disable-setuid-sandbox'],
    headless: 'new'
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 900 });
  await page.goto('file://' + path.resolve(htmlPath), { waitUntil: 'networkidle0' });

  const elements = await page.evaluate(() => {
    const results = [];
    const seen = new Set();

    function rgbToNorm(str) {
      const m = str.match(/(\d+)/g);
      if (!m || m.length < 3) return null;
      return { r: +m[0]/255, g: +m[1]/255, b: +m[2]/255, a: m[3] !== undefined ? +m[3] : 1 };
    }

    function walk(el, depth) {
      if (depth > 8) return;
      const style = getComputedStyle(el);
      const rect = el.getBoundingClientRect();
      if (rect.width < 2 || rect.height < 2) return;
      if (rect.top > 1200) return;

      const key = `${Math.round(rect.x)},${Math.round(rect.y)},${Math.round(rect.width)},${Math.round(rect.height)}`;
      if (seen.has(key)) return;
      seen.add(key);

      const bg = rgbToNorm(style.backgroundColor);
      const hasBg = bg && (bg.r < 0.99 || bg.g < 0.99 || bg.b < 0.99);
      const isText = el.childNodes.length === 1 && el.childNodes[0].nodeType === 3 && el.textContent.trim();
      const radius = parseFloat(style.borderRadius) || 0;
      const borderW = parseFloat(style.borderWidth) || 0;
      const borderColor = borderW > 0 ? rgbToNorm(style.borderColor) : null;

      // Shadow detection
      const shadow = style.boxShadow !== 'none';

      if (isText) {
        const color = rgbToNorm(style.color);
        results.push({
          type: 'text',
          x: Math.round(rect.x), y: Math.round(rect.y),
          w: Math.round(rect.width), h: Math.round(rect.height),
          text: el.textContent.trim(),
          fontSize: parseFloat(style.fontSize),
          fontWeight: parseInt(style.fontWeight) >= 600 ? 'bold' : 'normal',
          color,
          name: el.tagName.toLowerCase() + (el.className ? '.' + String(el.className).split(' ')[0] : '')
        });
      } else if (hasBg || borderW > 0 || shadow || el.tagName === 'INPUT' || el.tagName === 'BUTTON') {
        results.push({
          type: 'rect',
          x: Math.round(rect.x), y: Math.round(rect.y),
          w: Math.round(rect.width), h: Math.round(rect.height),
          bg: hasBg ? bg : { r: 1, g: 1, b: 1, a: 1 },
          radius: Math.round(radius),
          border: borderColor,
          borderWidth: borderW,
          name: el.tagName.toLowerCase() + (el.className ? '.' + String(el.className).split(' ')[0] : '')
        });
      }

      for (const child of el.children) {
        walk(child, depth + 1);
      }
    }

    walk(document.body, 0);
    return results;
  });

  await browser.close();
  return elements;
}

class FigmaMCP {
  constructor(channel) {
    this.channel = channel;
    this.tid = 0;
    this.proc = spawn(BUN, ['run', MCP_SERVER], {
      stdio: ['pipe', 'pipe', 'pipe'],
      env: { ...process.env, PATH: '/home/aimchn/.bun/bin:' + process.env.PATH, BUN_INSTALL: '/home/aimchn/.bun' }
    });
    this.rl = readline.createInterface({ input: this.proc.stdout });
  }

  send(msg) {
    this.proc.stdin.write(JSON.stringify(msg) + '\n');
  }

  recv(timeout = 15000) {
    return new Promise((resolve) => {
      const timer = setTimeout(() => resolve(null), timeout);
      this.rl.once('line', (line) => {
        clearTimeout(timer);
        try { resolve(JSON.parse(line)); } catch { resolve(null); }
      });
    });
  }

  async init() {
    this.send({ jsonrpc: '2.0', id: 0, method: 'initialize', params: { protocolVersion: '2024-11-05', capabilities: {}, clientInfo: { name: 'html2figma', version: '1.0' } } });
    await this.recv(10000);
    this.send({ jsonrpc: '2.0', method: 'notifications/initialized' });
    await new Promise(r => setTimeout(r, 4000));
  }

  async call(name, args) {
    this.tid++;
    this.send({ jsonrpc: '2.0', id: this.tid, method: 'tools/call', params: { name, arguments: args } });
    const r = await this.recv(15000);
    if (!r) return null;
    const text = r?.result?.content?.[0]?.text || '';
    const m = text.match(/"id":"([^"]+)"/);
    return { text, nodeId: m ? m[1] : null };
  }

  close() { this.proc.kill(); }
}

(async () => {
  const [,, htmlPath, channel, frameName = 'Design'] = process.argv;
  if (!htmlPath || !channel) {
    console.error('Usage: node html-to-figma.js design.html <channel> [frame-name]');
    process.exit(1);
  }

  console.log('📐 Extracting elements from HTML...');
  const elements = await extractElements(htmlPath);
  console.log(`   Found ${elements.length} elements`);

  console.log('🔌 Connecting to Figma MCP...');
  const figma = new FigmaMCP(channel);
  await figma.init();
  await figma.call('join_channel', { channel });

  // Find bounding box
  let minX = Infinity, minY = Infinity, maxX = 0, maxY = 0;
  for (const el of elements) {
    minX = Math.min(minX, el.x);
    minY = Math.min(minY, el.y);
    maxX = Math.max(maxX, el.x + el.w);
    maxY = Math.max(maxY, el.y + el.h);
  }
  const fw = maxX - minX + 40;
  const fh = maxY - minY + 40;

  // Create main frame
  console.log(`📱 Creating frame "${frameName}" (${fw}x${fh})...`);
  const frame = await figma.call('create_frame', { x: 0, y: 0, width: fw, height: fh, name: frameName });
  if (frame?.nodeId) {
    await figma.call('set_fill_color', { nodeId: frame.nodeId, r: 1, g: 1, b: 1, a: 1 });
  }

  // Create elements
  let created = 0;
  for (const el of elements) {
    const x = el.x - minX + 20;
    const y = el.y - minY + 20;

    if (el.type === 'rect') {
      const r = await figma.call('create_rectangle', { x, y, width: el.w, height: el.h, name: el.name });
      if (r?.nodeId) {
        await figma.call('set_fill_color', { nodeId: r.nodeId, ...el.bg });
        if (el.radius > 0) await figma.call('set_corner_radius', { nodeId: r.nodeId, radius: el.radius });
        if (el.border) await figma.call('set_stroke_color', { nodeId: r.nodeId, ...el.border, weight: el.borderWidth });
      }
      created++;
    } else if (el.type === 'text') {
      await figma.call('create_text', { x, y, content: el.text, fontSize: el.fontSize || 14, name: el.name });
      created++;
    }

    process.stdout.write(`\r   ${created}/${elements.length} elements`);
  }

  console.log(`\n🎉 Done! Created ${created} elements in Figma.`);
  figma.close();
})();
