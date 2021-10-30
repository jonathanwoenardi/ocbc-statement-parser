# TODO

- [x] Parse transactions.
- [x] Parse final account balances.
- [ ] Parse date.
- [ ] Use pandas.DataFrame
- [ ] Handle additional edge cases. I found that there are worse variants of the merging column cases (e.g. more than 2 columns merged into one). From my own testing parsing 62 monthly statements (297 transaction tables), 11 of them are still not handled properly (~95% succesful table rate, ~80% succesful statement rate). There are few possible solutions:
    - Check how the header row is combined and then deduce which column need to be splitted. However, there is an extreme case where 4 columns are combined but only 2 of them have some values. It will be hard to decide which columns those values actually belong to.
    - Investigate how to [specify column separators](https://camelot-py.readthedocs.io/en/master/user/advanced.html#specify-column-separators).
- [ ] Add some tests that does not involve my own personal data.
