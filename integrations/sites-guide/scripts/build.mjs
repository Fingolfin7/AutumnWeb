import { mkdir, copyFile } from 'node:fs/promises';
await mkdir('dist/server', {recursive:true});
await copyFile('src/worker.mjs', 'dist/server/index.js');
