/* Second sector of the spare AP VM block. Only an explicit automatic
 * record opts in. Neither a missing record nor a failed read starts a scan. */
#define INDEX_VM_SLOT 0x7e00
#define INDEX_AUTO 0x58444941
#define INDEX_MANUAL 0x5844494d
