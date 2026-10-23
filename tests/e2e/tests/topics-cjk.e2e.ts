import { beforeEach, describe, test } from '@e2e-dev/web';
import type { Browser, Locator } from '@e2e-dev/web';
import { expect } from 'e2e';
import { api, stubExternalAssets } from './helpers';

// 中文课题名回归：slugify_topic 曾把任意中文课题名在 ASCII 槽位里塌缩成同一个
// id（纯中文名甚至是空串），第二个中文课题必撞「课题 ID 已存在」。修复后的语义：
//   - 异名异 id（中文名各自得到带确定性短哈希后缀的课题 id）
//   - 同名同 id（重复创建仍被「课题 ID 已存在」拒绝）
//   - 纯 ASCII 名称的 slug 行为不变
// 用例名与课题名全部独立于其它文件，用例之间无顺序依赖（内容层在一次运行内共享）。
describe('topics with CJK names', () => {
  beforeEach(async ({ browser, app }) => {
    await stubExternalAssets(browser);
    await app.open('/');
  });

  function topicButton(browser: Browser, name: string): Locator {
    return browser.locator('button.tv-topic').filter({ hasText: name });
  }

  async function createTopic(screen: any, browser: Browser, name: string): Promise<void> {
    await screen.getByRole('button', '新建课题').tap();
    await expect(browser.locator('.tv-modal')).toBeVisible();
    await screen.getByPlaceholder(/例如：Seedance 2\.0/).fill(name);
    await screen.getByRole('button', '创建课题').tap();
  }

  test('creates two Chinese-named topics, each with its own id', async ({ screen, browser, app }) => {
    for (const name of ['机器学习', '翻译实践']) {
      await createTopic(screen, browser, name);
      await expect(browser.locator('.tv-toast')).toContainText(`已创建课题「${name}」`);
      await expect(topicButton(browser, name)).toBeVisible();
    }

    const { status, data } = await api('GET', '/api/topics');
    expect(status).toBe(200);
    const ml = data.topics.find((t: { name: string }) => t.name === '机器学习');
    const tr = data.topics.find((t: { name: string }) => t.name === '翻译实践');
    expect(ml?.id).toMatch(/^t-[0-9a-f]{8}$/);
    expect(tr?.id).toMatch(/^t-[0-9a-f]{8}$/);
    expect(ml.id).not.toBe(tr.id);
  });

  test('still rejects creating the same Chinese name with the duplicate error', async ({ screen, browser, app }) => {
    await createTopic(screen, browser, '中文重名演练');
    await expect(browser.locator('.tv-toast')).toContainText('已创建课题「中文重名演练」');

    // 同名第二次：最终课题 id 相同，必须仍被「课题 ID 已存在」拦下
    await createTopic(screen, browser, '中文重名演练');
    await expect(browser.locator('.tv-modal .tv-field-error')).toContainText('课题 ID 已存在');

    await browser.locator('.tv-modal').getByRole('button', '取消').tap();
    const { data } = await api('GET', '/api/topics');
    const same = data.topics.filter((t: { name: string }) => t.name === '中文重名演练');
    expect(same).toHaveLength(1);
  });

  test('renames a topic to a Chinese display name without changing its id', async ({ screen, browser, app }) => {
    await createTopic(screen, browser, 'E2E CJK Rename');
    await expect(browser.locator('.tv-toast')).toContainText('已创建课题「E2E CJK Rename」');

    const item = browser.locator('.tv-topic-item').filter({ hasText: 'E2E CJK Rename' });
    await item.hover();
    await screen.getByRole('button', { name: '重命名课题「E2E CJK Rename」' }).tap();
    const modal = browser.locator('.tv-modal');
    await expect(modal).toContainText('重命名课题');
    await browser.locator('.tv-modal input').first().fill('中文显示名');
    await modal.getByRole('button', '保存修改').tap();

    await expect(browser.locator('.tv-toast')).toContainText('课题已改名为「中文显示名」');
    await expect(topicButton(browser, '中文显示名')).toBeVisible();

    const { data } = await api('GET', '/api/topics');
    const renamed = data.topics.find((t: { id: string }) => t.id === 'e2e-cjk-rename');
    expect(renamed?.name).toBe('中文显示名');
  });
});
