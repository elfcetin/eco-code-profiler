export const SAMPLES = [
  {
    name: 'find_pair',
    code: `def find_pair(numbers, target):
    for i in range(len(numbers)):
        for j in range(i + 1, len(numbers)):
            if numbers[i] + numbers[j] == target:
                return (i, j)
    return None
`,
  },
  {
    name: 'find_duplicates',
    code: `def find_duplicates(items):
    duplicates = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if items[i] == items[j] and items[i] not in duplicates:
                duplicates.append(items[i])
    return duplicates
`,
  },
  {
    name: 'build_report',
    code: `def build_report(records):
    report = ""
    for record in records:
        report += f"{record} (toplam {len(records)} kayıt)\\n"
    return report
`,
  },
  {
    name: 'total',
    code: `def total(values):
    return sum(values)
`,
  },
]
