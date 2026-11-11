# TypeScript 全栈开发实践

TypeScript 提供了强类型约束，消灭了运行时的类型不匹配错误。

```typescript
interface User {
  id: number;
  name: string;
}
```

## 最佳实践

使用 Zod 运行时契约验证接口边界输入。
