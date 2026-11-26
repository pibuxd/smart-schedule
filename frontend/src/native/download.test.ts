import { beforeEach, describe, expect, it, vi } from 'vitest'

const writeFile = vi.fn<(options: { data: string; encoding?: string }) => Promise<{ uri: string }>>(async () => ({
  uri: 'file:///cache/godziny.csv',
}))
const share = vi.fn(async () => undefined)
const send = vi.fn()

vi.mock('@capacitor/filesystem', () => ({ Directory: { Cache: 'CACHE' }, Filesystem: { writeFile } }))
vi.mock('@capacitor/share', () => ({ Share: { share } }))
vi.mock('../api/http', () => ({ ApiError: class extends Error {}, send }))

const { shareFile } = await import('./download')

describe('shareFile', () => {
  beforeEach(() => vi.clearAllMocks())

  it("keeps the file's own bytes, with the UTF-8 mark Excel needs for Polish letters", async () => {
    const csv = new Uint8Array([0xef, 0xbb, 0xbf, ...new TextEncoder().encode('Imię;Godziny\nŁucja Żak;8\n')])
    send.mockResolvedValue(new Response(csv, { status: 200 }))

    await shareFile('/api/manager/hours.csv', 'godziny.csv')

    const [{ data, encoding }] = writeFile.mock.calls[0]
    expect(encoding).toBeUndefined() // base64: written as bytes
    expect(Uint8Array.from(atob(data), (c) => c.charCodeAt(0))).toEqual(csv)
    expect(share).toHaveBeenCalledWith(expect.objectContaining({ files: ['file:///cache/godziny.csv'] }))
  })
})
