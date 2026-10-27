import { beforeEach, describe, test } from '@e2e-dev/web';
import type { Browser, Locator } from '@e2e-dev/web';
import { expect } from 'e2e';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { api, stubExternalAssets, VAULT_ROOT } from './helpers';

// 课题行的「切换」按钮：与悬停才露出的重命名/删除按钮同名，用 .tv-topic 类圈出来
function topicButton(browser: Browser, name: string): Locator {
  return browser.locator('button.tv-topic').filter({ hasText: name });
}

describe('topics', () => {
  beforeEach(async ({ browser, app }) => {
    await stubExternalAssets(browser);
    await app.open('/');
  });

  test('creates a topic and switches to it', async ({ screen, browser, app }) => {
    await screen.getByRole('button', '新建课题').tap();
    await expect(browser.locator('.tv-modal')).toBeVisible();
    // 输入用英文命名：服务端会把名称 slug 化成课题 id，中文会全部塌缩成一个词
    await screen.getByPlaceholder(/例如：Seedance 2\.0/).fill('E2E Smoke Topic');
    await screen.getByPlaceholder(/这个课题收集什么内容/).fill('e2e 创建流程演练');
    await screen.getByRole('button', '创建课题').tap();

    await expect(browser.locator('.tv-toast')).toContainText('已创建课题「E2E Smoke Topic」');
    await expect(topicButton(browser, 'E2E Smoke Topic')).toBeVisible();
    // 新课题自动成为当前课题，空课题显示空状态
    await expect(screen.getByRole('heading', '「E2E Smoke Topic」还是空的')).toBeVisible();

    const { status, data } = await api('GET', '/api/topics');
    expect(status).toBe(200);
    const created = data.topics.find((t: { id: string }) => t.id === 'e2e-smoke-topic');
    expect(created?.name).toBe('E2E Smoke Topic');
    expect(created?.description).toBe('e2e 创建流程演练');
  });

  test('renames a topic without changing its id', async ({ screen, browser, app }) => {
    await screen.getByRole('button', '新建课题').tap();
    await screen.getByPlaceholder(/例如：Seedance 2\.0/).fill('E2E Rename Me');
    await screen.getByRole('button', '创建课题').tap();
    await expect(browser.locator('.tv-toast')).toContainText('已创建课题「E2E Rename Me」');

    // 悬停课题行露出操作按钮
    const item = browser.locator('.tv-topic-item').filter({ hasText: 'E2E Rename Me' });
    await item.hover();
    await screen.getByRole('button', { name: '重命名课题「E2E Rename Me」' }).tap();

    const modal = browser.locator('.tv-modal');
    await expect(modal).toContainText('重命名课题');
    await expect(modal).toContainText('e2e-rename-me'); // 弹窗标注课题 ID 不变
    await browser.locator('.tv-modal input').first().fill('E2E Renamed Topic');
    await browser.locator('.tv-modal textarea').fill('改名后的描述');
    await screen.getByRole('button', '保存修改').tap();

    await expect(browser.locator('.tv-toast')).toContainText('课题已改名为「E2E Renamed Topic」');
    await expect(topicButton(browser, 'E2E Renamed Topic')).toBeVisible();

    const { data } = await api('GET', '/api/topics');
    const renamed = data.topics.find((t: { id: string }) => t.id === 'e2e-rename-me');
    expect(renamed?.name).toBe('E2E Renamed Topic');
    expect(renamed?.description).toBe('改名后的描述');
  });

  test('deletes an empty topic without confirmation checkbox', async ({ screen, browser, app }) => {
    await screen.getByRole('button', '新建课题').tap();
    await screen.getByPlaceholder(/例如：Seedance 2\.0/).fill('E2E Short Lived');
    await screen.getByRole('button', '创建课题').tap();
    await expect(screen.getByRole('heading', '「E2E Short Lived」还是空的')).toBeVisible();

    const item = browser.locator('.tv-topic-item').filter({ hasText: 'E2E Short Lived' });
    await item.hover();
    await screen.getByRole('button', { name: '删除课题「E2E Short Lived」' }).tap();

    const modal = browser.locator('.tv-modal');
    await expect(modal).toContainText('这是一个空课题，删除后随时可以重新新建');
    await modal.getByRole('button', '删除课题').tap();

    await expect(browser.locator('.tv-toast')).toContainText('已删除课题「E2E Short Lived」');
    await expect(topicButton(browser, 'E2E Short Lived')).toHaveCount(0);
    const { data } = await api('GET', '/api/topics');
    expect(data.topics.find((t: { id: string }) => t.id === 'e2e-short-lived')).toBeUndefined();
  });

  test('deleting a non-empty topic requires the ack and removes its posts and media', async ({ screen, browser, app }) => {
    // 种子课题 e2e-scratch 带一条收藏 + 一个本地媒体文件
    const item = browser.locator('.tv-topic-item').filter({ hasText: 'E2E 删除陪练' });
    await item.hover();
    await screen.getByRole('button', { name: '删除课题「E2E 删除陪练」' }).tap();

    const modal = browser.locator('.tv-modal');
    await expect(modal).toContainText('这个课题下还有 1 条收藏');
    const deleteButton = modal.getByRole('button', '删除课题和 1 条收藏');
    await expect(deleteButton).toBeDisabled();

    await modal.getByLabel('我确认连同这 1 条收藏一起删除').check();
    await expect(deleteButton).toBeEnabled();
    await deleteButton.tap();

    await expect(browser.locator('.tv-toast')).toContainText('已删除课题「E2E 删除陪练」及其 1 条收藏');
    await expect(topicButton(browser, 'E2E 删除陪练')).toHaveCount(0);

    const topics = await (await fetch(`${app.baseUrl}/api/topics`)).json();
    expect(topics.topics.find((t: { id: string }) => t.id === 'e2e-scratch')).toBeUndefined();
    const posts = await (await fetch(`${app.baseUrl}/api/posts`)).json();
    expect(posts.posts.find((p: { uid: string }) => p.uid === 'e2e-scratch__x__1780000000003')).toBeUndefined();
    expect(
      existsSync(path.join(VAULT_ROOT, 'data/media/e2e/seed-scratch.png')),
    ).toBe(false);
  });
});
