import { beforeEach, describe, test } from '@e2e-dev/web';
import type { Browser, Locator } from '@e2e-dev/web';
import { expect } from 'e2e';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { stubExternalAssets, VAULT_ROOT } from './helpers';

// 课题行 = 切换按钮 + 悬停才露出的重命名/删除按钮（三者的可访问名都含课题名，
// 必须用 .tv-topic 类把「切换」按钮单独圈出来，否则 role 查询会命中 3 个节点）。
function topicButton(browser: Browser, name: string): Locator {
  return browser.locator('button.tv-topic').filter({ hasText: name });
}

describe('library', () => {
  beforeEach(async ({ browser, app }) => {
    await stubExternalAssets(browser);
    await app.open('/');
  });

  test('starts on the default empty topic and lists seeded topics with counts', async ({ screen, browser }) => {
    // 首个课题是 inbox（未归类），没有内容时显示空状态
    await expect(screen.getByRole('heading', '「未归类」还是空的')).toBeVisible();
    await expect(topicButton(browser, 'E2E 采集场')).toBeVisible();
    await expect(topicButton(browser, 'E2E 图书馆')).toBeVisible();
    await expect(screen.getByText('本地已沉淀 6 条')).toBeVisible();

    await topicButton(browser, 'E2E 采集场').tap();
    // 顶部标题的可访问名带条数后缀（如 “E2E 采集场 3”），用正则匹配
    await expect(screen.getByRole('heading', { name: /E2E 采集场/ })).toBeVisible();
    // 三条种子帖都在：视频（B站）/ 图集（小红书）/ 文字（X）
    await expect(screen.getByRole('heading', 'E2E 灯光师手记：一间小房间的布光方案')).toBeVisible();
    await expect(screen.getByRole('heading', 'E2E 咖啡拉花入门笔记')).toBeVisible();
    await expect(screen.getByRole('heading', 'E2E 选题会的三条纪律')).toBeVisible();
  });

  test('switches to list view and re-sorts by author', async ({ screen, browser }) => {
    await topicButton(browser, 'E2E 采集场').tap();
    await screen.getByRole('button', { name: '列表' }).tap();
    await expect(browser.locator('.tv-row')).toHaveCount(3);
    // 默认「最近收藏」：B站视频（addedAt 最新）在最前
    await expect(browser.locator('.tv-row').first()).toContainText('E2E 灯光师手记');

    await screen.getByRole('button', /最近收藏/).tap();
    await screen.getByRole('button', '按作者').tap();
    // zh 排序：阿真 < 李光明 < 王采
    await expect(browser.locator('.tv-row').first()).toContainText('E2E 咖啡拉花入门笔记');
  });

  test('filters by platform and type and clears all filters', async ({ screen, browser }) => {
    await topicButton(browser, 'E2E 采集场').tap();
    await expect(browser.locator('.tv-card')).toHaveCount(3);

    const sidebar = browser.locator('aside.tv-side');
    await sidebar.getByRole('button', /B站/).tap();
    await expect(browser.locator('.tv-card')).toHaveCount(1);
    await expect(screen.getByRole('heading', 'E2E 灯光师手记：一间小房间的布光方案')).toBeVisible();

    await sidebar.getByRole('button', /B站/).tap();
    await sidebar.getByRole('button', { name: /图片/ }).tap();
    await expect(browser.locator('.tv-card')).toHaveCount(1);
    await expect(screen.getByRole('heading', 'E2E 咖啡拉花入门笔记')).toBeVisible();

    await screen.getByRole('button', '清除全部').tap();
    await expect(browser.locator('.tv-card')).toHaveCount(3);
  });

  test('search finds a post by title keyword', async ({ screen, browser }) => {
    await topicButton(browser, 'E2E 采集场').tap();
    await screen.getByPlaceholder(/搜索作者、标题、关键词/).fill('拉花');
    await expect(browser.locator('.tv-card')).toHaveCount(1);
    await expect(screen.getByRole('heading', 'E2E 咖啡拉花入门笔记')).toBeVisible();
  });

  test('search reaches the transcript full text', async ({ screen, browser }) => {
    await topicButton(browser, 'E2E 采集场').tap();
    // 「夸克星门」只出现在口播转写文本里，标题/正文/关键词都没有
    await screen.getByPlaceholder(/搜索作者、标题、关键词/).fill('夸克星门');
    await expect(browser.locator('.tv-card')).toHaveCount(1);
    await expect(screen.getByRole('heading', 'E2E 灯光师手记：一间小房间的布光方案')).toBeVisible();
  });

  test('a search without matches offers clearing the filter', async ({ screen, browser }) => {
    await topicButton(browser, 'E2E 采集场').tap();
    await screen.getByPlaceholder(/搜索作者、标题、关键词/).fill('绝不存在的搜索词zzz');
    await expect(screen.getByRole('heading', '没有匹配的收藏')).toBeVisible();
    await screen.getByRole('button', '清除筛选').tap();
    await expect(browser.locator('.tv-card')).toHaveCount(3);
  });

  test('detail shows title, stats and the transcript tab', async ({ screen, browser }) => {
    await topicButton(browser, 'E2E 采集场').tap();
    await screen.getByRole('heading', 'E2E 灯光师手记：一间小房间的布光方案').tap();

    await expect(browser.locator('.tv-detail-title')).toHaveText('E2E 灯光师手记：一间小房间的布光方案');
    // 收藏时点快照：12345 浏览显示为 1.2万
    await expect(browser.locator('.tv-detail-stats')).toContainText('1.2万');
    await expect(browser.locator('.tv-detail-stats')).toContainText('浏览');

    await screen.getByRole('button', '转写').tap();
    await expect(browser.locator('.tv-transcript')).toContainText('夸克星门独家转写标记：三点布光从主光开始。');

    await screen.getByRole('button', '原文').tap();
    await expect(browser.locator('.tv-detail-copy')).toContainText('raw: 三点布光。');

    await screen.getByRole('button', '中文').tap();
    await expect(browser.locator('.tv-detail-copy')).toContainText('小房间布光要从主光开始');
  });

  test('remembers the active topic across a reload (localStorage)', async ({ screen, browser }) => {
    await topicButton(browser, 'E2E 图书馆').tap();
    await expect(screen.getByRole('heading', { name: /E2E 图书馆/ })).toBeVisible();

    await browser.reload();
    await expect(screen.getByRole('heading', { name: /E2E 图书馆/ })).toBeVisible();
    await expect(browser.locator('.tv-card')).toHaveCount(2);
  });

  test('edits a post and the change persists on the server', async ({ screen, browser, app }) => {
    await topicButton(browser, 'E2E 图书馆').tap();
    await screen.getByRole('heading', 'E2E 待编辑的旧笔记').tap();
    await screen.getByRole('button', { name: '编辑', exact: true }).tap();

    // EditModal 没有 label 关联，按 .tv-edit-modal 内的 CSS 顺序取字段
    await expect(browser.locator('.tv-edit-modal input').first()).toHaveValue('E2E 待编辑的旧笔记');
    await browser.locator('.tv-edit-modal input').first().fill('E2E 已编辑的笔记标题');
    await browser.locator('.tv-edit-modal textarea').first().fill('编辑后的正文内容。');
    await browser.locator('.tv-edit-modal input').nth(1).fill('检索, e2e标签');
    await screen.getByRole('button', '保存修改').tap();

    await expect(browser.locator('.tv-toast')).toContainText('修改已保存');
    await expect(browser.locator('.tv-detail-title')).toHaveText('E2E 已编辑的笔记标题');

    const res = await fetch(`${app.baseUrl}/api/posts`);
    const data = await res.json();
    const post = data.posts.find((p: { uid: string }) => p.uid === 'e2e-lib__x__1780000000002');
    expect(post.title).toBe('E2E 已编辑的笔记标题');
    expect(post.body).toBe('编辑后的正文内容。');
    expect(post.keywords).toEqual(['检索', 'e2e标签']);
    expect(post.editedAt).toBeGreaterThan(0);
  });

  test('deletes a post with its local media after explicit confirmation', async ({ screen, browser, app }) => {
    await topicButton(browser, 'E2E 图书馆').tap();
    const card = browser.locator('.tv-card').filter({ hasText: 'E2E 待删除的图集笔记' });
    await card.hover();
    await card.getByRole('button', { name: '删除这条收藏' }).tap();

    const confirm = browser.locator('.tv-confirm');
    await expect(confirm).toContainText('E2E 待删除的图集笔记');
    await expect(confirm).toContainText('同时删除 1 个本地文件');
    // 未勾选确认时删除按钮保持禁用
    await expect(confirm.getByRole('button', '删除')).toBeDisabled();
    await confirm.getByLabel('我确认删除，不可恢复').check();
    await confirm.getByRole('button', '删除').tap();

    await expect(browser.locator('.tv-toast')).toContainText('已删除「E2E 待删除的图集笔记」');
    await expect(browser.locator('.tv-card')).toHaveCount(1);

    const res = await fetch(`${app.baseUrl}/api/posts`);
    const data = await res.json();
    expect(data.posts.find((p: { uid: string }) => p.uid === 'e2e-lib__xiaohongshu__note777')).toBeUndefined();
    // withMedia 默认勾选：封面文件要从内容层一并清掉
    expect(existsSync(path.join(VAULT_ROOT, 'data/media/e2e/seed-delete.png'))).toBe(false);
  });
});
