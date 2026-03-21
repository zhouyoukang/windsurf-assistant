/**
 * Webpack Config — 结构消解层 (L1)
 * 
 * 将5个源模块 + 所有内部依赖合并为单一文件
 * 消除模块边界、文件名、import/export结构
 * 为后续混淆层提供无结构的原始材料
 */
const path = require('path');

module.exports = {
  target: 'node',
  mode: 'production',
  entry: './src/extension.js',
  output: {
    path: path.resolve(__dirname, 'dist'),
    filename: 'extension.js',
    libraryTarget: 'commonjs2',
    clean: true,
  },
  externals: {
    vscode: 'commonjs vscode',
  },
  node: {
    __dirname: false,   // 保留运行时真实路径 (wisdom_bundle.json依赖此路径)
    __filename: false,
  },
  resolve: {
    extensions: ['.js', '.json'],
  },
  optimization: {
    minimize: false,            // 不用terser — javascript-obfuscator接管
    concatenateModules: true,   // Scope hoisting: 尽可能合并模块作用域
    usedExports: true,          // Tree shaking: 标记未使用导出
  },
  devtool: false,  // 绝不生成source map
  stats: 'errors-warnings',
};
