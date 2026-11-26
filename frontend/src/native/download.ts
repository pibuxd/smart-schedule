import { Directory, Filesystem } from '@capacitor/filesystem'
import { Share } from '@capacitor/share'

import { ApiError, send } from '../api/http'

/**
 * A file from the API in the iOS and Android apps. A download link cannot work there (the session is in a header,
 * and a WebView does not save files), so the app fetches the file, keeps it in its cache and opens the system's
 * share sheet: save it to Files or Drive, or send it by e-mail. The web version keeps its link.
 */
export async function shareFile(url: string, fileName: string): Promise<void> {
  const response = await send(url)
  if (!response.ok) throw new ApiError(response.status, undefined)
  // The file's own bytes (base64, as Filesystem writes binary data): reading it as text would drop the CSV's UTF-8
  // mark, and Excel would then show Polish letters wrong.
  const { uri } = await Filesystem.writeFile({
    path: fileName,
    data: toBase64(new Uint8Array(await response.arrayBuffer())),
    directory: Directory.Cache,
  })
  await Share.share({ title: fileName, files: [uri], dialogTitle: fileName })
}

export function toBase64(bytes: Uint8Array): string {
  let binary = ''
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000))
  return btoa(binary)
}
