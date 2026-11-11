import * as argon2 from '@node-rs/argon2';
import bcrypt from 'bcryptjs';

export async function verifyPassword(plain: string, hashed: string): Promise<boolean> {
  if (!hashed || !plain) {
    return false;
  }

  if (hashed.startsWith('$argon2id$') || hashed.startsWith('$argon2i$') || hashed.startsWith('$argon2d$')) {
    try {
      return await argon2.verify(hashed, plain);
    } catch {
      return false;
    }
  }

  if (hashed.startsWith('$2a$') || hashed.startsWith('$2b$') || hashed.startsWith('$2y$')) {
    try {
      return bcrypt.compareSync(plain, hashed);
    } catch {
      return false;
    }
  }

  return false;
}

export async function hashPassword(plain: string): Promise<string> {
  // Use argon2id with standard OWASP / pwdlib parameters
  return argon2.hash(plain, {
    algorithm: 2, // Argon2id
    memoryCost: 65536,
    timeCost: 3,
    parallelism: 4,
  });
}
