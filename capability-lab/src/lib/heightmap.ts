export type HeightmapData = {
  width: number
  height: number
  values: Float32Array
}

export async function imageFileToHeightmap(file: File): Promise<HeightmapData> {
  const bitmap = await createImageBitmap(file)
  const size = 96
  const canvas = document.createElement('canvas')
  canvas.width = size
  canvas.height = size
  const ctx = canvas.getContext('2d', { willReadFrequently: true })
  if (!ctx) throw new Error('Could not read image')

  ctx.drawImage(bitmap, 0, 0, size, size)
  const { data } = ctx.getImageData(0, 0, size, size)
  const values = new Float32Array(size * size)

  for (let i = 0; i < size * size; i += 1) {
    const o = i * 4
    const luma = (0.299 * data[o] + 0.587 * data[o + 1] + 0.114 * data[o + 2]) / 255
    values[i] = luma
  }

  return { width: size, height: size, values }
}

export function makeDemoHeightmap(): HeightmapData {
  const width = 64
  const height = 64
  const values = new Float32Array(width * height)
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const nx = x / (width - 1) - 0.5
      const ny = y / (height - 1) - 0.5
      const r = Math.sqrt(nx * nx + ny * ny)
      const ring = Math.max(0, 1 - Math.abs(r - 0.28) * 8)
      const blob = Math.exp(-r * r * 10) * 0.85
      values[y * width + x] = Math.min(1, blob + ring * 0.65)
    }
  }
  return { width, height, values }
}
