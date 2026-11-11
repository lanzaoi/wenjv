import sharp from 'sharp';

export async function runSharpSpike(): Promise<void> {
  // Create a 100x100 solid color image buffer
  const initialBuffer = await sharp({
    create: {
      width: 100,
      height: 100,
      channels: 3,
      background: { r: 255, g: 0, b: 0 },
    },
  })
    .png()
    .toBuffer();

  // Test resize and webp conversion
  const resizedWebp = await sharp(initialBuffer)
    .resize(50, 50)
    .webp({ quality: 80 })
    .toBuffer();

  const metadata = await sharp(resizedWebp).metadata();
  if (metadata.width !== 50 || metadata.height !== 50 || metadata.format !== 'webp') {
    throw new Error(`Sharp spike failed: width=${metadata.width}, height=${metadata.height}, format=${metadata.format}`);
  }
}
