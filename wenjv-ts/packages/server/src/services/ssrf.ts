import dns from 'node:dns/promises';
import net from 'node:net';

export function isPrivateIp(ip: string): boolean {
  let targetIp = ip.trim();

  // Normalize IPv6 mapped IPv4 address: ::ffff:192.168.1.1 or ::ffff:7f00:1
  if (targetIp.toLowerCase().startsWith('::ffff:')) {
    const rest = targetIp.slice(7);
    if (net.isIPv4(rest)) {
      targetIp = rest;
    } else {
      const hexParts = rest.split(':');
      if (hexParts.length === 2) {
        const p1 = parseInt(hexParts[0] || '0', 16);
        const p2 = parseInt(hexParts[1] || '0', 16);
        targetIp = `${(p1 >> 8) & 0xff}.${p1 & 0xff}.${(p2 >> 8) & 0xff}.${p2 & 0xff}`;
      }
    }
  }

  if (net.isIPv4(targetIp)) {
    const parts = targetIp.split('.').map(Number);
    const [p0, p1, p2, p3] = [parts[0] ?? 0, parts[1] ?? 0, parts[2] ?? 0, parts[3] ?? 0];

    // 0.0.0.0/8 (Current network)
    if (p0 === 0) return true;
    // 10.0.0.0/8 (Private)
    if (p0 === 10) return true;
    // 100.64.0.0/10 (Shared Address Space / CGNAT RFC 6598: 100.64.0.0 - 100.127.255.255)
    if (p0 === 100 && p1 >= 64 && p1 <= 127) return true;
    // 127.0.0.0/8 (Loopback)
    if (p0 === 127) return true;
    // 169.254.0.0/16 (Link-local & AWS metadata 169.254.169.254)
    if (p0 === 169 && p1 === 254) return true;
    // 172.16.0.0/12 (Private)
    if (p0 === 172 && p1 >= 16 && p1 <= 31) return true;
    // 192.0.0.0/24 (IETF Protocol Assignments)
    if (p0 === 192 && p1 === 0 && p2 === 0) return true;
    // 192.0.2.0/24 (TEST-NET-1)
    if (p0 === 192 && p1 === 0 && p2 === 2) return true;
    // 192.168.0.0/16 (Private)
    if (p0 === 192 && p1 === 168) return true;
    // 198.18.0.0/15 (Network Benchmark Tests: 198.18.0.0 - 198.19.255.255)
    if (p0 === 198 && (p1 === 18 || p1 === 19)) return true;
    // 198.51.100.0/24 (TEST-NET-2)
    if (p0 === 198 && p1 === 51 && p2 === 100) return true;
    // 203.0.113.0/24 (TEST-NET-3)
    if (p0 === 203 && p1 === 0 && p2 === 113) return true;
    // 224.0.0.0/4 (Multicast: 224 - 239)
    if (p0 >= 224 && p0 <= 239) return true;
    // 240.0.0.0/4 (Reserved: 240 - 255)
    if (p0 >= 240) return true;
    // 255.255.255.255 (Broadcast)
    if (p0 === 255 && p1 === 255 && p2 === 255 && p3 === 255) return true;

    return false;
  }

  if (net.isIPv6(targetIp)) {
    const norm = targetIp.toLowerCase();
    if (norm === '::1' || norm === '::') return true;
    if (norm.startsWith('fc') || norm.startsWith('fd')) return true; // fc00::/7 (Unique local)
    if (norm.startsWith('fe8') || norm.startsWith('fe9') || norm.startsWith('fea') || norm.startsWith('feb')) return true; // fe80::/10 (Link-local)
    if (norm.startsWith('ff')) return true; // ff00::/8 (Multicast)
    if (norm.startsWith('64:ff9b:')) return true; // NAT64
    if (norm.startsWith('100::')) return true; // Discard-only prefix
    if (norm.startsWith('2001:db8:')) return true; // Documentation
    if (norm.startsWith('2001:10:') || norm.startsWith('2001:20:')) return true; // Benchmarking / ORCHIDv2
  }

  return false;
}

export async function validateSafeUrl(rawUrl: string): Promise<string> {
  let parsed: URL;
  try {
    parsed = new URL(rawUrl);
  } catch {
    throw new Error(`Invalid URL: ${rawUrl}`);
  }

  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    throw new Error(`Unsupported protocol: ${parsed.protocol}`);
  }

  const hostname = parsed.hostname.toLowerCase();

  // Block localhost and internal cloud metadata hostnames directly
  if (
    hostname === 'localhost' ||
    hostname === 'metadata' ||
    hostname === 'metadata.google.internal' ||
    hostname.endsWith('.localhost') ||
    hostname.endsWith('.local') ||
    hostname.endsWith('.internal')
  ) {
    throw new Error(`Restricted hostname: ${hostname}`);
  }

  // Handle direct IP address as hostname (including numeric formats)
  if (/^\d+$/.test(hostname)) {
    const intVal = parseInt(hostname, 10);
    const ipStr = `${(intVal >> 24) & 0xff}.${(intVal >> 16) & 0xff}.${(intVal >> 8) & 0xff}.${intVal & 0xff}`;
    if (isPrivateIp(ipStr)) {
      throw new Error(`SSRF blocked: numeric IP resolves to private IP ${ipStr}`);
    }
  }

  if (isPrivateIp(hostname)) {
    throw new Error(`SSRF blocked: direct private IP ${hostname}`);
  }

  // Resolve DNS to verify all A and AAAA records
  let addresses: Array<{ address: string; family: number }> = [];
  try {
    addresses = await dns.lookup(hostname, { all: true });
  } catch (err: unknown) {
    throw new Error(`DNS resolution failed for ${hostname}: ${err instanceof Error ? err.message : String(err)}`);
  }

  if (addresses.length === 0) {
    throw new Error(`DNS resolution returned no addresses for ${hostname}`);
  }

  for (const addr of addresses) {
    if (isPrivateIp(addr.address)) {
      throw new Error(`SSRF blocked: ${hostname} resolves to private IP ${addr.address}`);
    }
  }

  return parsed.toString();
}

/**
 * Perform safe HTTP GET fetching with per-hop redirect re-validation.
 * Prevents SSRF attacks via open redirects to cloud metadata or internal network addresses.
 */
export async function safeFetch(
  rawUrl: string,
  init: RequestInit = {},
  maxRedirects = 5
): Promise<Response> {
  let currentUrl = await validateSafeUrl(rawUrl);
  let redirectsRemaining = maxRedirects;

  while (true) {
    const response = await fetch(currentUrl, {
      ...init,
      redirect: 'manual',
    });

    if (
      [301, 302, 303, 307, 308].includes(response.status) &&
      response.headers.has('location')
    ) {
      if (redirectsRemaining <= 0) {
        throw new Error('Too many redirects');
      }
      redirectsRemaining--;
      const location = response.headers.get('location')!;
      const nextUrl = new URL(location, currentUrl).toString();
      currentUrl = await validateSafeUrl(nextUrl);
      continue;
    }

    return response;
  }
}
