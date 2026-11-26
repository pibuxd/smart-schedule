import { Directory, Encoding, Filesystem } from '@capacitor/filesystem'
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
  const { uri } = await Filesystem.writeFile({
    path: fileName,
    data: await response.text(),
    directory: Directory.Cache,
    encoding: Encoding.UTF8,
  })
  await Share.share({ title: fileName, files: [uri], dialogTitle: fileName })
}
