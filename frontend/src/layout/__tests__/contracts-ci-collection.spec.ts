import { execFileSync } from 'node:child_process'
import { copyFileSync, mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { expect, it } from 'vitest'

// 真实运行 package 脚本与生产配置；独立夹具不污染工作树，也不递归运行本测试。
it('本地契约快检收集共享目录任意深度的新测试，失败能够阻断命令', () => {
  const frontend = resolve(dirname(fileURLToPath(import.meta.url)), '../../..')
  const temporaryRoot = resolve(frontend, '../.local/tmp/ai-agent')
  mkdirSync(temporaryRoot, {recursive:true})
  const fixture = mkdtempSync(resolve(temporaryRoot, 'contracts-collection-'))
  const write = (path: string, source: string) => {
    const full = resolve(fixture,path)
    mkdirSync(dirname(full), {recursive:true})
    writeFileSync(full, source)
  }
  try {
    for (const config of ['vitest.config.ts','vitest.contracts.config.ts']) copyFileSync(resolve(frontend,config), resolve(fixture,config))
    symlinkSync(resolve(frontend,'node_modules'), resolve(fixture,'node_modules'), 'dir')
    const scripts = JSON.parse(readFileSync(resolve(frontend,'package.json'),'utf8')).scripts
    write('package.json',JSON.stringify({type:'module',scripts:{'test:contracts':scripts['test:contracts']}}))
    const selected = [
      'src/layout/__tests__/nested/new.spec.ts',
      'src/components/Direct.spec.ts',
      'src/components/widget/__tests__/nested/new.test.ts',
      'src/directives/__tests__/nested/new.spec.ts',
      'src/utils/__tests__/dateTime.spec.ts',
      'src/composables/__tests__/useTheme.spec.ts',
    ]
    const pass = 'import {it,expect} from "vitest";it("CI collection probe",()=>expect(true).toBe(true))'
    selected.forEach(path => write(path,pass))
    write('src/views/__tests__/business.spec.ts','throw new Error("business test is outside focused contracts")')
    const report = resolve(fixture,'report.json')
    const args = ['run','test:contracts','--','--reporter=json',`--outputFile=${report}`,'--minWorkers=1','--maxWorkers=1']
    const run = () => execFileSync('npm',args,{cwd:fixture,encoding:'utf8',stdio:'pipe',timeout:30000})
    run()
    const results = () => JSON.parse(readFileSync(report,'utf8'))
    expect(results().testResults.map((test: {name:string}) => test.name.replace(fixture+'/', '')).sort()).toEqual([...selected].sort())
    expect(results().numPassedTests).toBe(selected.length)
    write(selected[2],pass.replace('toBe(true)','toBe(false)'))
    expect(run).toThrow()
    expect(results().numFailedTests).toBe(1)
    expect(results().testResults.find((test: {name:string}) => test.name.endsWith(selected[2])).status).toBe('failed')
  } finally {
    rmSync(fixture,{recursive:true,force:true})
  }
},90000)
