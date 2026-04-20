#!/usr/bin/env node
// Рендерит HTML файл в PNG через Chrome
// Usage: node render.js input.html output.png [width] [height]
const puppeteer = require('puppeteer-core');
const path = require('path');

(async () => {
  const [,, input, output, w = '1440', h = '900'] = process.argv;
  if (!input || !output) { console.error('Usage: node render.js input.html output.png'); process.exit(1); }

  const browser = await puppeteer.launch({
    executablePath: '/usr/bin/google-chrome',
    args: ['--no-sandbox', '--disable-setuid-sandbox'],
    headless: 'new'
  });
  const page = await browser.newPage();
  await page.setViewport({ width: +w, height: +h });
  await page.goto('file://' + path.resolve(input), { waitUntil: 'networkidle0' });
  await page.screenshot({ path: output, fullPage: true });
  await browser.close();
  console.log(`✅ ${output}`);
})();
