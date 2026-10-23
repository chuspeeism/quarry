import type { Browser } from '@e2e-dev/web';
import { spawn, type ChildProcess } from 'node:child_process';
import { mkdirSync, rmSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

/** tests/e2e 项目根（package.json / e2e.config.ts 所在目录）。 */
export const PROJECT_ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
/** 仓库根（产品层）：tests/e2e 向上两级。 */
export const REPO_ROOT = path.dirname(path.dirname(PROJECT_ROOT));
/** 测试专用内容层：与 e2e.config.ts 保持同一默认值。 */
export const VAULT_ROOT = process.env.QUARRY_E2E_VAULT ?? '/tmp/quarry-e2e-vault';

const APP_ORIGIN = 'http://127.0.0.1:6002';

export type ApiResult = { status: number; data: any };

/** 直连本地后端 API（仅 127.0.0.1），用于断言服务端真实状态。 */
export async function api(
  method: 'GET' | 'POST' | 'PATCH' | 'DELETE',
  pathname: string,
  body?: unknown,
): Promise<ApiResult> {
  const res = await fetch(APP_ORIGIN + pathname, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let data: any = null;
  try {
    data = await res.json();
  } catch {
    data = null;
  }
  return { status: res.status, data };
}

/**
 * 把 index.html 引用的 unpkg CDN 脚本与 Google Fonts 拦到本地副本（node_modules 里
 * 钉死同版本），保证测试零外网依赖、完全确定。必须在 app.open() 之前注册。
 */
export async function stubExternalAssets(browser: Browser): Promise<void> {
  const vendor = (file: string) => path.relative(PROJECT_ROOT, path.join(PROJECT_ROOT, 'node_modules', file));
  await browser.route('**unpkg.com/**', async (route) => {
    const url = route.request.url;
    if (url.includes('react@18.3.1/umd/react.development.js')) {
      await route.fulfill({ path: vendor('react/umd/react.development.js') });
    } else if (url.includes('react-dom@18.3.1/umd/react-dom.development.js')) {
      await route.fulfill({ path: vendor('react-dom/umd/react-dom.development.js') });
    } else if (url.includes('@babel/standalone@7.29.0/babel.min.js')) {
      await route.fulfill({ path: vendor('@babel/standalone/babel.min.js') });
    } else {
      await route.abort();
    }
  });
  await browser.route('**fonts.googleapis.com/**', async (route) => {
    await route.fulfill({ body: '', contentType: 'text/css' });
  });
  await browser.route('**fonts.gstatic.com/**', async (route) => {
    await route.fulfill({ body: '' });
  });
}

export interface SecondServer {
  baseUrl: string;
  close(): Promise<void>;
}

/**
 * 在另一个端口上再起一个后端实例（同一内容层或全新内容层），用于验证
 * 「重启服务后状态还在」与「首启空库」这类跨进程流程。测试结束负责收尾。
 */
export async function startSecondServer(options: {
  port: number;
  vault: string;
  seed?: boolean;
}): Promise<SecondServer> {
  if (options.seed) {
    rmSync(options.vault, { recursive: true, force: true });
    mkdirSync(options.vault, { recursive: true });
    const { execFileSync } = await import('node:child_process');
    execFileSync('python3', [path.join(PROJECT_ROOT, 'scripts', 'seed_vault.py'), options.vault]);
  }
  const child: ChildProcess = spawn('python3', [path.join(REPO_ROOT, 'server', 'server.py')], {
    cwd: REPO_ROOT,
    env: { ...process.env, PORT: String(options.port), QUARRY_VAULT: options.vault, AI_ENGINE: 'none' },
    stdio: 'ignore',
  });
  const baseUrl = `http://127.0.0.1:${options.port}`;
  const deadline = Date.now() + 15_000;
  for (;;) {
    if (child.exitCode !== null) {
      throw new Error(`second server on :${options.port} exited early with ${child.exitCode}`);
    }
    try {
      const res = await fetch(`${baseUrl}/api/meta`);
      if (res.ok) break;
    } catch {
      /* not up yet */
    }
    if (Date.now() > deadline) {
      child.kill('SIGTERM');
      throw new Error(`second server on :${options.port} did not become ready in 15s`);
    }
    await new Promise((r) => setTimeout(r, 200));
  }
  return {
    baseUrl,
    async close() {
      child.kill('SIGTERM');
      await new Promise<void>((resolve) => {
        const timer = setTimeout(() => {
          child.kill('SIGKILL');
          resolve();
        }, 3000);
        child.once('exit', () => {
          clearTimeout(timer);
          resolve();
        });
      });
    },
  };
}
