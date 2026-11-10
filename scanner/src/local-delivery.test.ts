import { expect, test, vi } from 'vitest';
import { sendToTelegram } from './telegram';

test('all alert delivery prints locally without consulting credentials or network', async () => {
  const output = vi.spyOn(process.stdout, 'write').mockImplementation(() => true);
  const network = vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('network forbidden'));
  try {
    await sendToTelegram([{ text: 'synthetic travel signal', photos: [] }], []);
    expect(output).toHaveBeenCalledWith('synthetic travel signal\n');
    expect(network).not.toHaveBeenCalled();
  } finally {
    output.mockRestore();
    network.mockRestore();
  }
});
