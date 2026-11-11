import { hashPassword, verifyPassword } from '../../../packages/server/src/auth/password.js';
import { createAccessToken, verifyAccessToken } from '../../../packages/server/src/auth/jwt.js';

export async function runAuthSpike(): Promise<void> {
  const plain = 'StrongSecretPassword!123';

  // 1. Hash with argon2id and verify
  const hashed = await hashPassword(plain);
  const isValid = await verifyPassword(plain, hashed);
  if (!isValid) {
    throw new Error('Argon2 password verification failed');
  }

  const isInvalid = await verifyPassword('wrongpassword', hashed);
  if (isInvalid) {
    throw new Error('Argon2 verified wrong password as true');
  }

  // 2. JWT issue and verify
  const token = await createAccessToken(42);
  const { userId } = await verifyAccessToken(token);
  if (userId !== 42) {
    throw new Error(`JWT verification failed: expected 42, got ${userId}`);
  }
}
