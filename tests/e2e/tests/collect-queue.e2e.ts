import { beforeEach, describe, test } from '@e2e-dev/web';
import { expect } from 'e2e';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { api, startSecondServer, stubExternalAssets, VAULT_ROOT } from './helpers';

const BILI_URL = 'https://www.bilibili.com/video/BV1E2EQueue1';
const XHS_URL = 'https://www.xiaohongshu.com/explore/note888e2e';

describe('collect modal and deferred queue', () => {
  beforeEach(async ({ browser, app }) => {
    await stubExternalAssets(browser);
    await app.open('/');
  });

  test('collect modal detects a single platform and disables actions when empty', async ({ screen, browser }) => {
    await screen.getByRole('button', '收藏链接').tap();
    const modal = browser.locator('.tv-modal');
    await expect(modal).toBeVisible();

    // 空输入：两个动作按钮都禁用
    await expect(screen.getByRole('button', /加入队列/)).toBeDisabled();
    await expect(screen.getByRole('button', /立即收藏/)).toBeDisabled();

    await screen.getByPlaceholder(/多行链接批量收藏/).fill(BILI_URL);
    await expect(browser.locator('.tv-detect-row')).toContainText('识别为');
    await expect(browser.locator('.tv-detect-row')).toContainText('B站');
    await expect(browser.locator('.tv-pill.on')).toHaveCount(1);
    await expect(screen.getByRole('button', /加入队列/)).toBeEnabled();

    // 收藏到课题的选择器带着全部课题，默认落在当前课题（未归类）
    await expect(screen.getByRole('combobox')).toBeVisible();
  });

  test('multi-line paste announces the batch and cancel adds nothing', async ({ screen, browser, app }) => {
    await screen.getByRole('button', '收藏链接').tap();
    await screen
      .getByPlaceholder(/多行链接批量收藏/)
      .fill(`${BILI_URL}\n${XHS_URL}`);
    await expect(browser.locator('.tv-detect-row')).toContainText('识别到 2 条链接');
    await expect(screen.getByRole('button', /加入队列 2 条/)).toBeVisible();

    await screen.getByRole('button', '取消').tap();
    await expect(browser.locator('.tv-modal')).toHaveCount(0);

    const queue = await (await fetch(`${app.baseUrl}/api/queue`)).json();
    expect(queue.items).toHaveLength(0);
    const posts = await (await fetch(`${app.baseUrl}/api/posts`)).json();
    expect(posts.count).toBe(6); // 只存链接的路径绝不创建帖子
  });

  test('「加入队列」stores the link only and the queue bar shows it', async ({ screen, browser, app }) => {
    await api('DELETE', '/api/queue');
    await screen.getByRole('button', '收藏链接').tap();
    await screen.getByPlaceholder(/多行链接批量收藏/).fill(BILI_URL);
    // 切到有内容的课题，验证队列条目带课题标签
    await screen.getByRole('combobox').selectOption({ label: 'E2E 采集场' });
    await screen.getByRole('button', /加入队列/).tap();

    await expect(browser.locator('.tv-toast')).toContainText('已加入队列 1 条');
    const bar = browser.locator('.tv-qbar');
    await expect(bar).toBeVisible();
    await expect(bar).toContainText('1 条待采集');

    // 展开列表：链接 + 课题标签
    await screen.getByRole('button', /展开 1 条/).tap();
    const item = browser.locator('.tv-qitem').filter({ hasText: 'BV1E2EQueue1' });
    await expect(item).toBeVisible();
    await expect(item).toContainText('E2E 采集场');

    // 队列落盘在内容层 data/queue.json
    const disk = JSON.parse(readFileSync(path.join(VAULT_ROOT, 'data', 'queue.json'), 'utf8'));
    expect(disk.items).toHaveLength(1);
    expect(disk.items[0].url).toBe(BILI_URL);
    expect(disk.items[0].topic).toBe('e2e-camp');
    expect(disk.items[0].status).toBe('queued');

    // 服务端没有建帖、没有开始采集
    const posts = await (await fetch(`${app.baseUrl}/api/posts`)).json();
    expect(posts.count).toBe(6);
    const queue = await (await fetch(`${app.baseUrl}/api/queue`)).json();
    expect(queue.draining).toBe(false);
  });

  test('deferring the same link twice is reported as a skip', async ({ screen, browser }) => {
    await api('DELETE', '/api/queue');
    await screen.getByRole('button', '收藏链接').tap();
    await screen.getByPlaceholder(/多行链接批量收藏/).fill(BILI_URL);
    await screen.getByRole('combobox').selectOption({ label: 'E2E 采集场' });
    await screen.getByRole('button', /加入队列/).tap();
    await expect(browser.locator('.tv-qbar')).toBeVisible();

    await screen.getByRole('button', '收藏链接').tap();
    await screen.getByPlaceholder(/多行链接批量收藏/).fill(BILI_URL);
    await screen.getByRole('combobox').selectOption({ label: 'E2E 采集场' });
    await screen.getByRole('button', /加入队列/).tap();
    await expect(browser.locator('.tv-toast')).toContainText('这些链接已经在队列里了');
    await expect(browser.locator('.tv-qbar')).toContainText('1 条待采集');
  });

  test('removes one queued link and clears the rest', async ({ screen, browser }) => {
    await api('DELETE', '/api/queue');
    await screen.getByRole('button', '收藏链接').tap();
    await screen
      .getByPlaceholder(/多行链接批量收藏/)
      .fill(`${BILI_URL}\n${XHS_URL}`);
    await screen.getByRole('button', /加入队列 2 条/).tap();
    await expect(browser.locator('.tv-qbar')).toContainText('2 条待采集');

    await screen.getByRole('button', /展开 2 条/).tap();
    await browser
      .locator('.tv-qitem')
      .filter({ hasText: 'note888e2e' })
      .getByRole('button', '移除')
      .tap();
    await expect(browser.locator('.tv-qbar')).toContainText('1 条待采集');
    await expect(browser.locator('.tv-qitem')).toHaveCount(1);

    await browser.locator('.tv-qbar').getByRole('button', /清空队列/).tap();
    await expect(browser.locator('.tv-qbar')).toHaveCount(0);
  });

  test('queued links survive a server restart', async ({ screen, browser, app }) => {
    await api('DELETE', '/api/queue');
    await screen.getByRole('button', '收藏链接').tap();
    await screen
      .getByPlaceholder(/多行链接批量收藏/)
      .fill(`${BILI_URL}\n${XHS_URL}`);
    await screen.getByRole('button', /加入队列 2 条/).tap();
    await expect(browser.locator('.tv-qbar')).toContainText('2 条待采集');

    // 用同一内容层再起一个后端实例 = 重启服务；队列在 data/queue.json 里应原样恢复
    const second = await startSecondServer({ port: 6033, vault: VAULT_ROOT });
    try {
      await app.open(`${second.baseUrl}/`);
      const bar = browser.locator('.tv-qbar');
      await expect(bar).toBeVisible();
      await expect(bar).toContainText('2 条待采集');
      await expect(bar).toContainText('链接已存好，不会开网页');
      await screen.getByRole('button', /展开 2 条/).tap();
      await expect(browser.locator('.tv-qitem').filter({ hasText: 'BV1E2EQueue1' })).toBeVisible();
      await expect(browser.locator('.tv-qitem').filter({ hasText: 'note888e2e' })).toBeVisible();
    } finally {
      await second.close();
    }
    // 收尾：把队列清干净，不给其它用例留状态
    await api('DELETE', '/api/queue');
  });
});
