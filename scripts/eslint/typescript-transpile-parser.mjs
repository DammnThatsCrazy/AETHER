import * as espree from 'espree';
import ts from 'typescript';


export function parseForESLint(code, options = {}) {
  const filePath = options.filePath ?? 'input.ts';
  const transpiled = ts.transpileModule(code, {
    fileName: filePath,
    compilerOptions: {
      target: ts.ScriptTarget.ES2022,
      module: ts.ModuleKind.ESNext,
      jsx: ts.JsxEmit.React,
      sourceMap: false,
    },
    reportDiagnostics: false,
    transformers: undefined,
  }).outputText;

  const ast = espree.parse(transpiled, {
    ecmaVersion: 'latest',
    sourceType: 'module',
    loc: true,
    range: true,
    tokens: true,
    comment: true,
  });

  return {
    ast,
    services: {
      isTranspiledTypeScript: true,
    },
  };
}

export default { parseForESLint };
