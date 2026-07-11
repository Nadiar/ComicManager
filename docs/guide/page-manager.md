# CBZ Page Manager

ComicManager includes a tool to manage the internal pages of your digital comic files. This lets you fix page order, remove unwanted content, and add missing pages without leaving the app.

![Page Manager Modal](/manage_pages.png)

---

## When to Use the Page Manager

The Page Manager is useful when:
- A comic was scanned out of order and pages need to be rearranged.
- The file contains ads, publisher catalogs, or other pages you want to strip out.
- A cover page is missing and you want to add it.
- You have duplicate pages from a bad scan.

For more severe issues (corrupt files, wrong issue entirely), re-importing the file is usually better than fixing it page by page.

---

## Features

- **Reorder Pages**: Drag-and-drop thumbnails to change the page order within the CBZ.
- **Delete Pages**: Select individual pages and remove them from the file. 
- **Add Pages**: Upload new image files to insert into the CBZ.
- **Lightbox Preview**: Click any thumbnail to see a full-size preview before making changes.

---

## How to Use

1. Go to the **Comic Detail** page for any digital comic.
2. Click **Manage Pages** under **Actions** to open the page manager modal.
3. The modal shows a thumbnail grid of all pages in the CBZ in their current order.
4. **To reorder**: Drag a thumbnail to its new position. The order updates live in the grid.
5. **To delete**: Click the red X icon on a thumbnail to mark it for removal. Marked pages show a red overlay. You can unmark a page by clicking again.
6. **To add pages**: Use the upload button to select one or more image files. Uploaded pages appear at the end of the grid and can be dragged into position.
7. Click **Save Changes** to write all edits to the CBZ file on disk.

---

## Automatic Updates After Saving

After saving, ComicManager automatically:

- Updates the **page count** in the database to match the new file.
- Clears the **cover image cache** so the new cover is used everywhere.

The `ComicInfo.xml` inside the CBZ is not rewritten by the page manager. The updated page count will be embedded the next time you run the Write step for that comic.

The comic's workflow state is not changed by page edits. It stays at whatever state it was in before.
