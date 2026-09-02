/** Display a stored 0..1 decimal score as a user-facing percentage.
 *
 * The receipt score arrives as a decimal string, and the frontend's money path
 * deliberately avoids JS floats. Moving the decimal point in text keeps the
 * exact digits the server sent while making the value easier to scan.
 */
export function accuracyPercent(score: string): string {
  if (!/^\d+(\.\d+)?$/.test(score)) return score

  const [whole, fraction = ''] = score.split('.')
  const point = whole.length + 2
  const digits = `${whole}${fraction}`.padEnd(point, '0')
  const percentWhole = digits.slice(0, point).replace(/^0+(?=\d)/, '')
  const percentFraction = digits.slice(point).replace(/0+$/, '')

  return percentFraction === '' ? `${percentWhole}%` : `${percentWhole}.${percentFraction}%`
}
