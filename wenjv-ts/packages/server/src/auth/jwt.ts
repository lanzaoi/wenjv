import * as jose from 'jose';
import { config } from '../config.js';

function getSecretKey(): Uint8Array {
  return new TextEncoder().encode(config.JWT_SECRET);
}

export async function createAccessToken(userId: number | string): Promise<string> {
  const secret = getSecretKey();
  return new jose.SignJWT({ sub: String(userId) })
    .setProtectedHeader({ alg: 'HS256' })
    .setAudience(config.JWT_AUDIENCE)
    .setIssuedAt()
    .setExpirationTime(`${config.JWT_EXPIRES_IN_SECONDS}s`)
    .sign(secret);
}

export async function verifyAccessToken(token: string): Promise<{ userId: number }> {
  const secret = getSecretKey();
  const { payload } = await jose.jwtVerify(token, secret, {
    audience: config.JWT_AUDIENCE,
  });

  const sub = payload.sub;
  if (!sub || !/^\d+$/.test(sub)) {
    throw new Error('Invalid or missing user ID in token');
  }

  const userId = Number.parseInt(sub, 10);
  if (!Number.isSafeInteger(userId) || userId <= 0) {
    throw new Error('Invalid user ID in token');
  }

  return { userId };
}
