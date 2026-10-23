import { afterAll, beforeAll, describe, test } from '@e2e-dev/web';
import type { Browser } from '@e2e-dev/web';
import { expect } from 'e2e';
import { mkdirSync, rmSync } from 'node:fs';
import { startSecondServer, stubExternalAssets, type SecondServer } from './helpers';

// 全新内容层（不灌种子）：验证首启空库与「删掉最后一个课题自动重建默认课题」。
// 这两个流程会毁掉内容层，所以用 6002 之外的后端实例 + 一次性临时内容层，跑完即焚。
const FRESH_VAULT = '/tmp/quarry-e2e-fresh-vault';

function topicButton(browser: Browser, name: string) {
  return browser.locator('button.tv-topic').filter({ hasText: name });
}

async function getJson(baseUrl: string, pathname: string): Promise<any> {
  return (await fetch(`${baseUrl}${pathname}`)).json();
}

describe('fresh vault', { serial: true }, () => {
  let server: SecondServer;

  beforeAll(async () => {
    rmSync(FRESH_VAULT, { recursive: true, force: true });
    mkdirSync(FRESH_VAULT, { recursive: true });
    server = await startSecondServer({ port: 6044, vault: FRESH_VAULT });
  });

  afterAll(async () => {
    await server?.close();
    rmSync(FRESH_VAULT, { recursive: true, force: true });
  });

  test('first boot initializes an empty default topic', async ({ browser, screen, app }) => {
    await stubExternalAssets(browser);
    await app.open(`${server.baseUrl}/`);

    await expect(topicButton(browser, '未归类')).toBeVisible();
    await expect(screen.getByRole('heading', '「未归类」还是空的')).toBeVisible();

    const meta = await getJson(server.baseUrl, '/api/meta');
    expect(meta.posts).toBe(0);
    expect(meta.topics).toBe(1);
    const topics = await getJson(server.baseUrl, '/api/topics');
    expect(topics.topics).toHaveLength(1);
    expect(topics.topics[0].id).toBe('inbox');
    expect(topics.topics[0].postCount).toBe(0);
  });

  test('deleting the last topic auto-recreates the default topic', async ({ browser, screen, app }) => {
    await stubExternalAssets(browser);
    await app.open(`${server.baseUrl}/`);

    // 建一个课题，此时库里两个课题
    await screen.getByRole('button', '新建课题').tap();
    await screen.getByPlaceholder(/例如：Seedance 2\.0/).fill('Only Child');
    await screen.getByRole('button', '创建课题').tap();
    await expect(screen.getByRole('heading', '「Only Child」还是空的')).toBeVisible();

    // 删掉默认课题（空课题，无需确认勾选）
    const inboxItem = browser.locator('.tv-topic-item').filter({ hasText: '未归类' });
    await inboxItem.hover();
    await screen.getByRole('button', { name: '删除课题「未归类」' }).tap();
    await browser.locator('.tv-modal').getByRole('button', '删除课题').tap();
    await expect(browser.locator('.tv-toast')).toContainText('已删除课题「未归类」');

    // 再删掉 Only Child —— 最后一个课题，服务端应自动重建默认课题
    const lastItem = browser.locator('.tv-topic-item').filter({ hasText: 'Only Child' });
    await lastItem.hover();
    await screen.getByRole('button', { name: '删除课题「Only Child」' }).tap();
    await browser.locator('.tv-modal').getByRole('button', '删除课题').tap();
    await expect(browser.locator('.tv-toast')).toContainText('已删除课题「Only Child」');

    await expect(topicButton(browser, '未归类')).toBeVisible();
    const meta = await getJson(server.baseUrl, '/api/meta');
    expect(meta.topics).toBe(1);
    const topics = await getJson(server.baseUrl, '/api/topics');
    expect(topics.topics[0].id).toBe('inbox');
    expect(topics.topics[0].name).toBe('未归类');
  });
});
