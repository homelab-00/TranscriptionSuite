/**
 * Read a fetch response body into memory, reporting the running byte count
 * (GH-318). For downloads that must be verified as a whole before a single
 * byte is written to disk - `Response.arrayBuffer()` does the same read but
 * says nothing until it is over.
 */

export async function readBodyWithProgress(
  body: ReadableStream<Uint8Array> | null,
  onProgress: (bytesReceived: number) => void,
): Promise<Buffer> {
  if (!body) throw new Error('Response had no body');
  const reader = body.getReader();
  const chunks: Buffer[] = [];
  let received = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    if (!value) continue;
    chunks.push(Buffer.from(value));
    received += value.length;
    try {
      onProgress(received);
    } catch {
      // Progress reporting must never fail the download it is watching.
    }
  }
  return Buffer.concat(chunks);
}
