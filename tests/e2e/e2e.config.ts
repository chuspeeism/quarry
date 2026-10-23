import type { E2EConfig } from 'e2e';
import { web } from '@e2e-dev/web';

// 内容层隔离：全部测试数据落在 /tmp 下的一次性目录（每次运行由 start-server.sh
// 清空重建），仓库内的默认内容层 ../vault 永不被触碰。
const vault = process.env.QUARRY_E2E_VAULT ?? '/tmp/quarry-e2e-vault';

export default {
  // 模型无关（无 agents 块）：全部测试只用 locators/screen + expect，不用 agent.act。
  targets: [
    {
      name: 'web',
      engine: web(),
      app: {
        // Quarry 后端的原生端口
        url: 'http://127.0.0.1:6002',
        command: {
          executable: 'bash',
          args: ['tests/e2e/scripts/start-server.sh'],
          cwd: '../..',
          env: {
            PORT: '6002',
            QUARRY_VAULT: vault,
            AI_ENGINE: 'none',
          },
          log: '.e2e/logs/app.log',
          shutdownTimeout: 10_000,
        },
      },
    },
  ],
  // 共享 16 GB 机器：单 worker、单浏览器，串行跑。
  workers: 1,
  retries: 0,
  // 前端是 Babel standalone 浏览器内编译，首屏编译要几秒，放宽断言预算。
  assertionTimeout: 15_000,
  actionTimeout: 15_000,
} satisfies E2EConfig;
